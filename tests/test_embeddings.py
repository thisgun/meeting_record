"""RAG 임베딩/청킹/검색 단위 테스트 (Ollama 호출은 더미로 대체)."""
from pathlib import Path

import numpy as np

from src import embeddings, storage


# 결정론적 더미 임베딩: 키워드 존재 여부로 차원을 채워 검색 랭킹을 검증 가능하게 한다.
_KEYWORDS = ["예산", "안전", "채용", "일정"]


def _fake_embed(texts, *, model="bge-m3", host="", batch_size=32, timeout=300.0):
    rows = []
    for t in texts:
        v = np.array([1.0 if kw in t else 0.0 for kw in _KEYWORDS], dtype=np.float32)
        if not v.any():
            v[0] = 0.01  # zero-norm 방지
        rows.append(v)
    arr = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def test_chunk_summary_splits_by_section() -> None:
    md = "## 개요\n- 배경\n\n## 결정 사항\n- 합의"
    chunks = embeddings.chunk_summary("예산 회의", md)
    assert len(chunks) == 2
    assert all(c.startswith("[회의: 예산 회의]") for c in chunks)
    assert "개요" in chunks[0]
    assert "결정 사항" in chunks[1]


def test_chunk_utterances_groups_and_keeps_start() -> None:
    utts = [
        {"speaker": f"사용자{i % 2 + 1}", "start_sec": float(i), "end_sec": i + 1,
         "text": "내용 " * 60}
        for i in range(10)
    ]
    chunks = embeddings.chunk_utterances("회의", utts)
    assert chunks
    assert chunks[0][0] == 0.0  # 첫 청크의 start_sec
    assert all(text.startswith("[회의: 회의]") for _start, text in chunks)


def test_chunk_utterances_skips_empty_text() -> None:
    utts = [
        {"speaker": "사용자1", "start_sec": 0.0, "end_sec": 1, "text": ""},
        {"speaker": "사용자2", "start_sec": 1.0, "end_sec": 2, "text": "유효한 발화"},
    ]
    chunks = embeddings.chunk_utterances("회의", utts)
    assert len(chunks) == 1
    assert "유효한 발화" in chunks[0][1]


def test_index_and_search_ranks_relevant_meeting_first(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embed)
    db = tmp_path / "m.db"
    storage.save_meeting(
        db, source_file="a.mp3", title="예산 회의",
        summary_md="## 개요\n예산 배정을 논의", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "예산 관련 발언"}],
    )
    storage.save_meeting(
        db, source_file="b.mp3", title="안전 회의",
        summary_md="## 개요\n안전 점검 강화", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "안전 관련 발언"}],
    )

    n = embeddings.index_all(db, verbose=False)
    assert n == 2

    hits = embeddings.search_chunks(db, "예산은 어떻게 됐나", top_k=3)
    assert hits
    assert hits[0]["title"] == "예산 회의"
    assert hits[0]["remote_post_id"] is None  # 아직 업로드 전


def test_is_indexable_rejects_failed_and_empty() -> None:
    assert embeddings.is_indexable("정상 회의", "## 개요\n충분히 긴 정상 요약입니다.")
    assert not embeddings.is_indexable("회의록 (자동 생성 실패)", "## 개요\n내용이 있어도 제목이 실패")
    assert not embeddings.is_indexable("회의", "_요약 파싱 실패: 어쩌고")
    assert not embeddings.is_indexable("회의", "짧음")  # 30자 미만


def test_index_skips_failed_meeting(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embed)
    db = tmp_path / "m.db"
    storage.save_meeting(
        db, source_file="ok.mp3", title="예산 회의",
        summary_md="## 개요\n예산 배정을 충분히 논의한 정상 회의입니다.", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "예산"}],
    )
    storage.save_meeting(
        db, source_file="bad.mp3", title="회의록 (자동 생성 실패)",
        summary_md="_요약 파싱 실패: JSON 오류_", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "내용"}],
    )
    n = embeddings.index_all(db, verbose=False)
    assert n == 1  # 실패 회의는 제외, 정상 1건만
    hits = embeddings.search_chunks(db, "예산", top_k=20)
    assert all(h["title"] != "회의록 (자동 생성 실패)" for h in hits)


def test_min_score_filters_low_scoring(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embed)
    db = tmp_path / "m.db"
    storage.save_meeting(
        db, source_file="a.mp3", title="예산 회의",
        summary_md="## 개요\n예산 배정을 충분히 논의했습니다.", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "예산 발언"}],
    )
    embeddings.index_all(db, verbose=False)
    # '안전' 질문은 '예산' 회의와 더미 임베딩상 직교(score 0) → min_score로 전부 제외
    hits = embeddings.search_chunks(db, "안전 점검", top_k=6, min_score=0.5)
    assert hits == []


def test_index_meeting_is_idempotent_without_force(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embed)
    db = tmp_path / "m.db"
    mid = storage.save_meeting(
        db, source_file="a.mp3", title="일정 회의",
        summary_md="## 개요\n일정 확정", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "일정 발언"}],
    )
    assert embeddings.index_meeting(db, mid) > 0
    assert embeddings.index_meeting(db, mid) == 0  # 이미 인덱싱됨


def test_matrix_cache_reflects_new_meetings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embed)
    embeddings.invalidate_matrix_cache()
    db = tmp_path / "m.db"
    storage.save_meeting(
        db, source_file="a.mp3", title="예산 회의",
        summary_md="## 개요\n예산 배정을 논의", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "예산"}],
    )
    embeddings.index_all(db, verbose=False)
    before = embeddings.search_chunks(db, "안전", top_k=20)

    storage.save_meeting(
        db, source_file="b.mp3", title="안전 회의",
        summary_md="## 개요\n안전 점검을 강화", duration_sec=10,
        utterances=[{"speaker": "사용자1", "start": 0, "end": 2, "text": "안전"}],
    )
    embeddings.index_all(db, verbose=False)
    after = embeddings.search_chunks(db, "안전", top_k=20)

    assert len(after) > len(before)  # 캐시가 새 청크를 반영
    assert any(h["title"] == "안전 회의" for h in after)
