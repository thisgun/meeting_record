"""그누보드5 게시판 시맨틱 검색 인덱서.

게시판 글(posts.php로 수집)을 청크로 잘라 bge-m3로 임베딩해 posts.db(SQLite)에
저장한다. 검색은 PHP(semantic_search.php)가 같은 DB를 읽어 직접 수행하므로,
여기서는 인덱싱만 담당한다(상시 Python 서비스 불필요).

임베딩은 L2 정규화되어 저장되므로 PHP 쪽은 쿼리 벡터만 정규화하면
내적 = 코사인 유사도가 된다.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import numpy as np

from .embeddings import embed_texts
from .storage import connect


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
    indexed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_post_chunks_board ON post_chunks(bo_table);
CREATE INDEX IF NOT EXISTS idx_post_chunks_model ON post_chunks(model);
"""

CHUNK_MAX_CHARS = 800
SNIPPET_CHARS = 200


def init_posts_schema(db_path) -> None:
    with connect(db_path) as conn:
        conn.executescript(POST_SCHEMA)


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
    verbose: bool = True,
) -> int:
    """게시판 1개를 전부 수집·임베딩해 posts.db에 재구축. 인덱싱된 글 수 반환."""
    init_posts_schema(db_path)

    rows: list[tuple] = []  # (wr_id, seq, subject, name, datetime, snippet, text)
    offset = 0
    while True:
        data = client.list_posts(bo_table, offset=offset, limit=page_size)
        posts = data.get("posts", [])
        if not posts:
            break
        for p in posts:
            subject = (p.get("subject") or "").strip()
            body = strip_html(p.get("content") or "")
            snippet = body[:SNIPPET_CHARS].strip() or subject
            for seq, ctext in enumerate(chunk_post(subject, body)):
                rows.append((
                    int(p["wr_id"]), seq, subject, p.get("name"),
                    p.get("datetime"), snippet, ctext,
                ))
        offset += len(posts)
        if offset >= int(data.get("total", 0)):
            break

    if not rows:
        with connect(db_path) as conn:
            conn.execute("DELETE FROM post_chunks WHERE bo_table = ?", (bo_table,))
        if verbose:
            print(f"  [post-index] {bo_table}: 글 없음 (인덱스 비움)")
        return 0

    arr = embed_texts([r[6] for r in rows], model=embed_model, host=host)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dim = int(arr.shape[1])

    with connect(db_path) as conn:
        conn.execute("DELETE FROM post_chunks WHERE bo_table = ?", (bo_table,))
        conn.executemany(
            """INSERT INTO post_chunks
                 (bo_table, wr_id, seq, subject, name, datetime, snippet, text,
                  embedding, dim, model, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (bo_table, wr_id, seq, subject, name, dt, snippet, text,
                 arr[i].tobytes(), dim, embed_model, now)
                for i, (wr_id, seq, subject, name, dt, snippet, text) in enumerate(rows)
            ],
        )

    n_posts = len({r[0] for r in rows})
    if verbose:
        print(f"  [post-index] {bo_table}: 글 {n_posts}개 / 청크 {len(rows)}개")
    return n_posts


def index_boards(
    client,
    boards,
    *,
    db_path,
    embed_model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    verbose: bool = True,
) -> dict[str, int]:
    """여러 게시판 인덱싱. {bo_table: 글 수} 반환."""
    result = {}
    for bo in boards:
        try:
            result[bo] = index_board(
                client, bo, db_path=db_path, embed_model=embed_model,
                host=host, verbose=verbose,
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
    scores = mat @ qvec

    best: dict[tuple, dict] = {}
    for c, s in zip(chunks, scores):
        score = float(s)
        if min_score and score < min_score:
            continue
        key = (c["bo_table"], c["wr_id"])
        if key not in best or score > best[key]["score"]:
            best[key] = {
                "bo_table": c["bo_table"], "wr_id": c["wr_id"],
                "subject": c["subject"], "name": c["name"],
                "datetime": c["datetime"], "snippet": c["snippet"],
                "score": score,
            }
    return sorted(best.values(), key=lambda d: -d["score"])[: max(1, int(top_k))]
