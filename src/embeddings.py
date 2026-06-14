"""RAG용 임베딩 인덱스 (Ollama + SQLite).

회의록(요약 섹션 + 발화 묶음)을 청크로 잘라 Ollama 임베딩 모델로 벡터화하고
meetings.db의 rag_chunks 테이블에 저장한다. 검색은 numpy 코사인 유사도
(전수 비교 — 회의 수백 건 규모에서는 충분히 빠름).

사용:
    from src.embeddings import index_all, search_chunks
    index_all(db_path, embed_model="bge-m3", host="http://127.0.0.1:11434")
    hits = search_chunks(db_path, "예산 관련 결정사항", embed_model=..., host=..., top_k=6)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np

from .storage import connect


RAG_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- 'summary' | 'utterance'
    seq INTEGER NOT NULL,
    start_sec REAL,                  -- utterance 청크의 시작 시각 (출처 표기용)
    text TEXT NOT NULL,
    embedding BLOB NOT NULL,         -- float32 little-endian, L2 정규화 저장
    dim INTEGER NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_meeting ON rag_chunks(meeting_id);
"""

# 청크 크기 (문자 기준 — 한국어 ~2.5자/토큰이므로 600자 ≈ 240토큰)
SUMMARY_CHUNK_MAX = 1200
UTTERANCE_CHUNK_MAX = 600
UTTERANCE_CHUNK_OVERLAP = 1  # 이전 청크의 마지막 발화 N개를 다음 청크에 중복 포함


def init_rag_schema(db_path) -> None:
    with connect(db_path) as conn:
        conn.executescript(RAG_SCHEMA)


# 요약 생성에 실패했거나 내용이 비어 검색 노이즈만 되는 회의를 인덱싱에서 제외하는 마커.
# 정상 요약은 수백 자이므로, 길이 기준은 사실상 '거의 빈 요약'만 걸러낸다(주력은 마커).
_LOW_QUALITY_MARKERS = ("자동 생성 실패", "요약 파싱 실패", "요약 생성 실패")
_MIN_SUMMARY_CHARS = 10


def is_indexable(title: str, summary_md: str) -> bool:
    """요약이 정상 생성된 회의인지. 실패/빈 요약은 인덱싱에서 제외한다."""
    title = (title or "").strip()
    summary = (summary_md or "").strip()
    if len(summary) < _MIN_SUMMARY_CHARS:
        return False
    haystack = f"{title}\n{summary}"
    return not any(marker in haystack for marker in _LOW_QUALITY_MARKERS)


# ── 청킹 ────────────────────────────────────────────────────────


def chunk_summary(title: str, summary_md: str) -> list[str]:
    """요약 마크다운을 '## 섹션' 단위로 분할. 각 청크에 회의 제목을 prefix."""
    sections = re.split(r"(?m)^(?=## )", summary_md.strip())
    chunks: list[str] = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        # 너무 긴 섹션은 추가 분할
        while len(sec) > SUMMARY_CHUNK_MAX:
            cut = sec.rfind("\n", 0, SUMMARY_CHUNK_MAX)
            if cut < SUMMARY_CHUNK_MAX // 2:
                cut = SUMMARY_CHUNK_MAX
            chunks.append(f"[회의: {title}]\n{sec[:cut].strip()}")
            sec = sec[cut:].strip()
        if sec:
            chunks.append(f"[회의: {title}]\n{sec}")
    return chunks


def chunk_utterances(title: str, utterances: list[dict]) -> list[tuple[float, str]]:
    """발화를 연속 묶음으로 청킹. (start_sec, text) 리스트 반환."""
    chunks: list[tuple[float, str]] = []
    buf: list[dict] = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        if not buf:
            return
        lines = [f"{u['speaker']}: {(u['text'] or '').strip()}" for u in buf]
        text = f"[회의: {title}]\n" + "\n".join(lines)
        chunks.append((float(buf[0]["start_sec"]), text))
        # 다음 청크에 마지막 발화를 overlap으로 남김
        buf = buf[-UTTERANCE_CHUNK_OVERLAP:] if UTTERANCE_CHUNK_OVERLAP else []
        buf_len = sum(len(u["text"] or "") for u in buf)

    for u in utterances:
        text = (u.get("text") or "").strip()
        if not text:
            continue
        buf.append(u)
        buf_len += len(text)
        if buf_len >= UTTERANCE_CHUNK_MAX:
            flush()
    # 남은 버퍼 (overlap만 남은 경우는 스킵)
    if buf and buf_len > 0 and len(buf) > UTTERANCE_CHUNK_OVERLAP:
        lines = [f"{u['speaker']}: {(u['text'] or '').strip()}" for u in buf]
        chunks.append((float(buf[0]["start_sec"]), f"[회의: {title}]\n" + "\n".join(lines)))
    elif buf and not chunks:
        lines = [f"{u['speaker']}: {(u['text'] or '').strip()}" for u in buf]
        chunks.append((float(buf[0]["start_sec"]), f"[회의: {title}]\n" + "\n".join(lines)))
    return chunks


# ── 임베딩 ──────────────────────────────────────────────────────


def embed_texts(
    texts: list[str],
    *,
    model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    batch_size: int = 32,
    timeout: float = 300.0,
) -> np.ndarray:
    """텍스트 리스트 → L2 정규화된 float32 행렬 (N, dim)."""
    try:
        from ollama import Client
    except ImportError as e:
        raise RuntimeError("ollama 패키지가 필요합니다: pip install ollama") from e

    client = Client(host=host, timeout=timeout)
    vecs: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client.embed(model=model, input=batch)
        embs = resp.get("embeddings") if isinstance(resp, dict) else resp.embeddings
        vecs.extend(embs)
    arr = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


# 검색용 청크 행렬 캐시. 매 질문마다 BLOB을 전부 디코딩하지 않도록
# (db_path, model)별로 (행렬, 메타, 청크수)를 메모리에 보관하고 청크 수가
# 바뀌면 무효화한다. 단일 프로세스(ask 1회/qa_watcher 폴링)에 충분.
_MATRIX_CACHE: dict[tuple[str, str], tuple[int, np.ndarray, list[dict]]] = {}


def _load_chunk_matrix(db_path, embed_model: str) -> tuple[np.ndarray, list[dict]]:
    """(행렬, 메타리스트) 반환. 청크 수가 그대로면 캐시 재사용."""
    with connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE model = ?", (embed_model,)
        ).fetchone()[0]

    key = (str(db_path), embed_model)
    cached = _MATRIX_CACHE.get(key)
    if cached and cached[0] == count:
        return cached[1], cached[2]

    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT c.id, c.meeting_id, c.kind, c.start_sec, c.text, c.embedding,
                      m.title, m.created_at, m.remote_post_id
               FROM rag_chunks c JOIN meetings m ON m.id = c.meeting_id
               WHERE c.model = ?""",
            (embed_model,),
        ).fetchall()
    if not rows:
        empty = np.empty((0, 0), dtype=np.float32)
        _MATRIX_CACHE[key] = (0, empty, [])
        return empty, []

    mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    meta = [{
        "chunk_id": r["id"], "meeting_id": r["meeting_id"], "kind": r["kind"],
        "start_sec": r["start_sec"], "text": r["text"], "title": r["title"],
        "created_at": r["created_at"], "remote_post_id": r["remote_post_id"],
    } for r in rows]
    _MATRIX_CACHE[key] = (count, mat, meta)
    return mat, meta


def invalidate_matrix_cache() -> None:
    """인덱싱 후 캐시 강제 무효화 (테스트/장시간 데몬용)."""
    _MATRIX_CACHE.clear()


# ── 인덱싱 ──────────────────────────────────────────────────────


def index_meeting(
    db_path,
    meeting_id: int,
    *,
    embed_model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    force: bool = False,
) -> int:
    """회의 1건을 청킹+임베딩하여 저장. 생성된 청크 수 반환 (이미 있고 force=False면 0)."""
    init_rag_schema(db_path)
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE meeting_id = ? AND model = ?",
            (int(meeting_id), embed_model),
        ).fetchone()[0]
        if existing and not force:
            return 0
        meeting = conn.execute(
            "SELECT id, title, summary_md FROM meetings WHERE id = ?", (int(meeting_id),)
        ).fetchone()
        if not meeting:
            raise ValueError(f"meeting_id={meeting_id} 없음")
        utts = conn.execute(
            "SELECT speaker, start_sec, text FROM utterances WHERE meeting_id = ? ORDER BY seq",
            (int(meeting_id),),
        ).fetchall()

    # 요약 실패/빈 회의는 검색 노이즈만 되므로 인덱싱하지 않는다 (기존 청크가 있으면 정리).
    if not is_indexable(meeting["title"], meeting["summary_md"]):
        if existing:
            with connect(db_path) as conn:
                conn.execute("DELETE FROM rag_chunks WHERE meeting_id = ?", (int(meeting_id),))
            invalidate_matrix_cache()
        return 0

    title = meeting["title"]
    items: list[tuple[str, float | None, str]] = []  # (kind, start_sec, text)
    for text in chunk_summary(title, meeting["summary_md"] or ""):
        items.append(("summary", None, text))
    for start_sec, text in chunk_utterances(title, [dict(u) for u in utts]):
        items.append(("utterance", start_sec, text))
    if not items:
        return 0

    arr = embed_texts([t for _, _, t in items], model=embed_model, host=host)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with connect(db_path) as conn:
        conn.execute("DELETE FROM rag_chunks WHERE meeting_id = ?", (int(meeting_id),))
        conn.executemany(
            """INSERT INTO rag_chunks
                 (meeting_id, kind, seq, start_sec, text, embedding, dim, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (int(meeting_id), kind, seq, start_sec, text,
                 arr[seq].tobytes(), int(arr.shape[1]), embed_model, now)
                for seq, (kind, start_sec, text) in enumerate(items)
            ],
        )
    invalidate_matrix_cache()
    return len(items)


def index_all(
    db_path,
    *,
    embed_model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    force: bool = False,
    verbose: bool = True,
) -> int:
    """미인덱싱(또는 모델이 바뀐) 회의를 모두 인덱싱. 처리한 회의 수 반환."""
    init_rag_schema(db_path)
    with connect(db_path) as conn:
        if force:
            rows = conn.execute("SELECT id, title, summary_md FROM meetings ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                """SELECT m.id, m.title, m.summary_md FROM meetings m
                   WHERE NOT EXISTS (
                       SELECT 1 FROM rag_chunks c
                       WHERE c.meeting_id = m.id AND c.model = ?)
                   ORDER BY m.id""",
                (embed_model,),
            ).fetchall()
    # not force: 저품질 회의는 호출 전에 걸러 매 폴링마다 재시도하지 않도록 한다.
    # force(재구축): 저품질 회의도 index_meeting을 거쳐 기존 청크를 정리한다.
    ids = [r["id"] for r in rows if force or is_indexable(r["title"], r["summary_md"])]
    done = 0
    for mid in ids:
        n = index_meeting(db_path, mid, embed_model=embed_model, host=host, force=True)
        done += 1
        if verbose:
            print(f"  [index] meeting {mid}: {n}청크")
    return done


# ── 검색 ────────────────────────────────────────────────────────


def search_chunks(
    db_path,
    query: str,
    *,
    embed_model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    top_k: int = 6,
    embed_timeout: float = 300.0,
    min_score: float = 0.0,
) -> list[dict]:
    """질문과 가장 유사한 청크 top_k 반환.

    반환 dict: meeting_id, kind, start_sec, text, score, title, created_at, remote_post_id
    """
    init_rag_schema(db_path)
    mat, meta = _load_chunk_matrix(db_path, embed_model)
    if not meta:
        return []

    qvec = embed_texts([query], model=embed_model, host=host, timeout=embed_timeout)[0]
    scores = mat @ qvec
    order = np.argsort(-scores)[: max(1, int(top_k))]

    out = []
    for i in order:
        score = float(scores[int(i)])
        if min_score and score < min_score:
            continue  # 점수 임계값 미만 청크 제외 (무관한 회의가 출처에 섞이는 것 방지)
        item = dict(meta[int(i)])
        item["score"] = score
        out.append(item)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from config import load_config

    cfg = load_config()
    n = index_all(cfg.db_path, embed_model=cfg.embed_model, host=cfg.ollama_host,
                  force="--rebuild" in sys.argv)
    print(f"인덱싱 완료: 회의 {n}건")
