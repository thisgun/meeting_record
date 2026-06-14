"""게시판 시맨틱 검색 인덱서 단위 테스트 (Ollama 호출은 더미로 대체)."""
from pathlib import Path

import numpy as np

from src import post_index


_KEYWORDS = ["반품", "교환", "배송", "회원", "비밀번호"]


def _fake_embed(texts, *, model="bge-m3", host="", batch_size=32, timeout=300.0):
    rows = []
    for t in texts:
        v = np.array([1.0 if kw in t else 0.0 for kw in _KEYWORDS], dtype=np.float32)
        if not v.any():
            v[0] = 0.01
        rows.append(v)
    arr = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


class FakeClient:
    """posts.php 응답을 흉내내는 더미 G5 클라이언트."""

    def __init__(self, posts):
        self._posts = posts

    def list_posts(self, bo_table, *, offset=0, limit=100):
        page = self._posts[offset:offset + limit]
        return {
            "bo_table": bo_table, "total": len(self._posts),
            "offset": offset, "count": len(page), "posts": page,
        }


def test_strip_html() -> None:
    assert post_index.strip_html("<p>안녕<br>하세요</p>") == "안녕\n하세요"
    assert "script" not in post_index.strip_html("<script>alert(1)</script>본문입니다")
    assert post_index.strip_html("&lt;태그&gt; &amp; 기호") == "<태그> & 기호"


def test_chunk_post_short_keeps_title() -> None:
    chunks = post_index.chunk_post("반품 정책", "7일 이내 반품 가능")
    assert len(chunks) == 1
    assert "반품 정책" in chunks[0]


def test_chunk_post_long_splits_with_title() -> None:
    chunks = post_index.chunk_post("긴 글", "가" * 2000, max_chars=800)
    assert len(chunks) >= 3
    assert all("긴 글" in c for c in chunks)


def test_index_and_search_ranks_relevant_first(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_index, "embed_texts", _fake_embed)
    db = tmp_path / "posts.db"
    posts = [
        {"wr_id": 1, "subject": "반품 정책", "content": "반품 신청 안내", "name": "관리자", "datetime": "2026-06-01"},
        {"wr_id": 2, "subject": "배송 공지", "content": "배송 지연 안내", "name": "관리자", "datetime": "2026-06-02"},
    ]
    n = post_index.index_board(FakeClient(posts), "free", db_path=db, verbose=False)
    assert n == 2

    hits = post_index.search_posts(db, "반품 환불 문의", top_k=5)
    assert hits
    assert hits[0]["wr_id"] == 1  # '반품' 글이 1위
    assert hits[0]["bo_table"] == "free"


def test_index_paginates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_index, "embed_texts", _fake_embed)
    db = tmp_path / "posts.db"
    posts = [
        {"wr_id": i, "subject": f"회원 안내 {i}", "content": "회원 등급", "name": "a", "datetime": "d"}
        for i in range(1, 6)
    ]
    # page_size=2로 강제 페이지네이션
    n = post_index.index_board(FakeClient(posts), "free", db_path=db, page_size=2, verbose=False)
    assert n == 5


def test_incremental_skips_unchanged(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []

    def counting_embed(texts, **kw):
        calls.append(len(texts))
        return _fake_embed(texts, **kw)

    monkeypatch.setattr(post_index, "embed_texts", counting_embed)
    db = tmp_path / "posts.db"
    posts = [{"wr_id": 1, "subject": "반품", "content": "내용", "name": "a", "datetime": "d"}]
    post_index.index_board(FakeClient(posts), "free", db_path=db, verbose=False)
    assert sum(calls) > 0
    calls.clear()
    # 동일 데이터 재인덱싱 → 재임베딩 호출 없음 (content_hash 동일)
    post_index.index_board(FakeClient(posts), "free", db_path=db, verbose=False)
    assert sum(calls) == 0


def test_incremental_reembeds_changed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_index, "embed_texts", _fake_embed)
    db = tmp_path / "posts.db"
    post_index.index_board(
        FakeClient([{"wr_id": 1, "subject": "반품", "content": "원본 내용", "name": "a", "datetime": "d"}]),
        "free", db_path=db, verbose=False,
    )
    post_index.index_board(
        FakeClient([{"wr_id": 1, "subject": "반품", "content": "수정된 내용입니다", "name": "a", "datetime": "d"}]),
        "free", db_path=db, verbose=False,
    )
    hits = post_index.search_posts(db, "반품", top_k=5)
    assert hits and "수정된" in hits[0]["snippet"]


def test_incremental_removes_deleted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_index, "embed_texts", _fake_embed)
    db = tmp_path / "posts.db"
    both = [
        {"wr_id": 1, "subject": "반품 정책", "content": "x", "name": "a", "datetime": "d"},
        {"wr_id": 2, "subject": "배송 안내", "content": "y", "name": "a", "datetime": "d"},
    ]
    post_index.index_board(FakeClient(both), "free", db_path=db, verbose=False)
    # 2번 글 삭제 후 재인덱싱 → 인덱스에서 제거
    post_index.index_board(FakeClient([both[0]]), "free", db_path=db, verbose=False)
    hits = post_index.search_posts(db, "배송", top_k=10)
    assert all(h["wr_id"] != 2 for h in hits)


def test_index_empty_board_clears(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_index, "embed_texts", _fake_embed)
    db = tmp_path / "posts.db"
    post_index.index_board(
        FakeClient([{"wr_id": 1, "subject": "반품", "content": "x", "name": "a", "datetime": "d"}]),
        "free", db_path=db, verbose=False,
    )
    assert post_index.search_posts(db, "반품")
    # 게시판이 비면 인덱스도 비워진다
    post_index.index_board(FakeClient([]), "free", db_path=db, verbose=False)
    assert post_index.search_posts(db, "반품") == []
