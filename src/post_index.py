"""그누보드5 게시판 시맨틱 검색 인덱서.

게시판 글(posts.php로 수집)을 청크로 잘라 bge-m3로 임베딩해 posts.db(SQLite)에
저장한다. 검색은 PHP(semantic_search.php)가 같은 DB를 읽어 직접 수행하므로,
여기서는 인덱싱만 담당한다(상시 Python 서비스 불필요).

임베딩은 L2 정규화되어 저장되므로 PHP 쪽은 쿼리 벡터만 정규화하면
내적 = 코사인 유사도가 된다.
"""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone

import numpy as np

from .storage import connect
from .vectorstore import cosine_topk, embed_texts


POST_SCHEMA = """
CREATE TABLE IF NOT EXISTS post_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bo_table TEXT NOT NULL,
    wr_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    subject TEXT NOT NULL,
    name TEXT,
    datetime TEXT,
    snippet TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL,
    dim INTEGER NOT NULL,
    model TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_post_chunks_board ON post_chunks(bo_table);
CREATE INDEX IF NOT EXISTS idx_post_chunks_model ON post_chunks(model);
"""

CHUNK_MAX_CHARS = 800
SNIPPET_CHARS = 200


def init_posts_schema(db_path) -> None:
    with connect(db_path) as conn:
        conn.executescript(POST_SCHEMA)
        # 기존 테이블 마이그레이션: content_hash 컬럼이 없으면 추가
        cols = {r[1] for r in conn.execute("PRAGMA table_info(post_chunks)")}
        if "content_hash" not in cols:
            conn.execute("ALTER TABLE post_chunks ADD COLUMN content_hash TEXT")


def _post_hash(subject: str, body: str) -> str:
    """글 변경 감지용 해시 (제목+본문)."""
    return hashlib.sha256(f"{subject}\x00{body}".encode("utf-8")).hexdigest()[:16]


def strip_html(text: str) -> str:
    """그누보드 에디터 HTML → 평문."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_post(subject: str, body: str, *, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """제목 + 본문을 청크로 분할. 각 청크에 제목을 prefix해 제목 의미를 반영한다."""
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not (subject or body):
        return []
    head = f"제목: {subject}\n" if subject else ""
    if len(body) <= max_chars:
        return [f"{head}{body}".strip()]
    chunks = []
    pos = 0
    while pos < len(body):
        seg = body[pos:pos + max_chars]
        chunks.append(f"{head}{seg}".strip())
        pos += max_chars
    return chunks


def index_board(
    client,
    bo_table: str,
    *,
    db_path,
    embed_model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    page_size: int = 100,
    force: bool = False,
    verbose: bool = True,
) -> int:
    """게시판 1개를 증분 인덱싱해 posts.db에 반영. 현재 글 수 반환.

    content_hash로 변경/신규 글만 재임베딩하고, 삭제된 글은 인덱스에서 제거한다.
    force=True면 전체를 다시 임베딩한다.
    """
    init_posts_schema(db_path)

    # 1) 게시판 글 전체 수집 (메타 + 변경 감지 해시)
    posts: list[dict] = []
    offset = 0
    while True:
        data = client.list_posts(bo_table, offset=offset, limit=page_size)
        page = data.get("posts", [])
        if not page:
            break
        for p in page:
            subject = (p.get("subject") or "").strip()
            body = strip_html(p.get("content") or "")
            posts.append({
                "wr_id": int(p["wr_id"]), "subject": subject, "body": body,
                "name": p.get("name"), "datetime": p.get("datetime"),
                "snippet": body[:SNIPPET_CHARS].strip() or subject,
                "hash": _post_hash(subject, body),
            })
        offset += len(page)
        if offset >= int(data.get("total", 0)):
            break

    current_ids = {p["wr_id"] for p in posts}

    # 2) 기존 인덱스의 글별 해시
    with connect(db_path) as conn:
        existing = {
            int(wr_id): h for wr_id, h in conn.execute(
                "SELECT DISTINCT wr_id, content_hash FROM post_chunks WHERE bo_table = ? AND model = ?",
                (bo_table, embed_model),
            )
        }

    deleted = set(existing) - current_ids
    changed = [p for p in posts if force or existing.get(p["wr_id"]) != p["hash"]]

    # 3) 변경/신규 글의 청크 임베딩
    chunk_rows: list[tuple] = []  # (wr_id, seq, subject, name, dt, snippet, text, hash)
    for p in changed:
        for seq, ctext in enumerate(chunk_post(p["subject"], p["body"])):
            chunk_rows.append((
                p["wr_id"], seq, p["subject"], p["name"], p["datetime"],
                p["snippet"], ctext, p["hash"],
            ))
    arr = embed_texts([r[6] for r in chunk_rows], model=embed_model, host=host) if chunk_rows else None

    # 4) DB 반영: 삭제 글 제거 + 변경 글 청크 교체
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        for wid in deleted:
            conn.execute("DELETE FROM post_chunks WHERE bo_table = ? AND wr_id = ?", (bo_table, wid))
        for wid in {p["wr_id"] for p in changed}:
            conn.execute("DELETE FROM post_chunks WHERE bo_table = ? AND wr_id = ?", (bo_table, wid))
        if chunk_rows:
            dim = int(arr.shape[1])
            conn.executemany(
                """INSERT INTO post_chunks
                     (bo_table, wr_id, seq, subject, name, datetime, snippet, text,
                      embedding, dim, model, indexed_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (bo_table, wr_id, seq, subject, name, dt, snippet, text,
                     arr[i].tobytes(), dim, embed_model, now, h)
                    for i, (wr_id, seq, subject, name, dt, snippet, text, h) in enumerate(chunk_rows)
                ],
            )

    if verbose:
        print(f"  [post-index] {bo_table}: 글 {len(current_ids)}개 "
              f"(변경/신규 {len(changed)}, 삭제 {len(deleted)})")
    return len(current_ids)


def index_boards(
    client,
    boards,
    *,
    db_path,
    embed_model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    force: bool = False,
    verbose: bool = True,
) -> dict[str, int]:
    """여러 게시판 인덱싱. {bo_table: 글 수} 반환."""
    result = {}
    for bo in boards:
        try:
            result[bo] = index_board(
                client, bo, db_path=db_path, embed_model=embed_model,
                host=host, force=force, verbose=verbose,
            )
        except Exception as e:
            print(f"  [post-index] {bo}: 실패 — {e}")
            result[bo] = -1
    return result


# 검색은 PHP가 담당하지만, 디버그/테스트용 파이썬 검색도 제공한다.
def search_posts(
    db_path,
    query: str,
    *,
    embed_model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict]:
    """게시글 시맨틱 검색 (글 단위 최고 점수). 디버그/검증용."""
    init_posts_schema(db_path)
    with connect(db_path) as conn:
        chunks = conn.execute(
            """SELECT bo_table, wr_id, subject, name, datetime, snippet, embedding
               FROM post_chunks WHERE model = ?""",
            (embed_model,),
        ).fetchall()
    if not chunks:
        return []

    mat = np.stack([np.frombuffer(c["embedding"], dtype=np.float32) for c in chunks])
    qvec = embed_texts([query], model=embed_model, host=host)[0]

    # 점수 내림차순으로 순회하며 글(bo_table, wr_id) 단위 최고 점수만 취해 top_k개 수집
    best: dict[tuple, dict] = {}
    for i, score in cosine_topk(mat, qvec, top_k=len(chunks), min_score=min_score):
        c = chunks[i]
        key = (c["bo_table"], c["wr_id"])
        if key not in best:
            best[key] = {
                "bo_table": c["bo_table"], "wr_id": c["wr_id"],
                "subject": c["subject"], "name": c["name"],
                "datetime": c["datetime"], "snippet": c["snippet"],
                "score": score,
            }
        if len(best) >= max(1, int(top_k)):
            break
    return list(best.values())
