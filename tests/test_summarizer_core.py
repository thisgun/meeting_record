"""summarizer.py 순수 함수 단위 테스트 (JSON 파싱·청킹·컨텍스트 추정).

Ollama 호출 없이 검증 가능한 로직만 다룬다 (네트워크/모델 불필요).
"""
import json

import pytest

from src import summarizer as S


# ── 시간/transcript 포맷 ──────────────────────────────────────
def test_fmt_time():
    assert S._fmt_time(0) == "00:00"
    assert S._fmt_time(65) == "01:05"
    assert S._fmt_time(3661) == "01:01:01"
    assert S._fmt_time(-5) == "00:00"


def test_format_transcript_skips_empty_and_includes_time():
    utts = [
        {"speaker": "사용자1", "text": "안녕", "start": 0, "end": 2},
        {"speaker": "사용자2", "text": "   ", "start": 2, "end": 3},   # 공백 → 제외
        {"speaker": "사용자2", "text": "네", "start": 3, "end": 5},
    ]
    assert S._format_transcript(utts) == "사용자1: 안녕\n사용자2: 네"
    timed = S._format_transcript(utts, include_time=True)
    assert "[00:00-00:02] 사용자1: 안녕" in timed
    assert len(timed.splitlines()) == 2


# ── _extract_json ────────────────────────────────────────────
def test_extract_json_clean():
    out = S._extract_json('{"title": "T", "summary_md": "본문"}')
    assert out == {"title": "T", "summary_md": "본문"}


def test_extract_json_codefenced():
    out = S._extract_json('```json\n{"title": "T", "summary_md": "본문"}\n```')
    assert out["summary_md"] == "본문"


def test_extract_json_truncated_recovers_summary():
    # 닫는 따옴표/중괄호 없이 잘린 응답 → 정규식 부분 추출
    raw = '{"title": "회의", "summary_md": "## 개요\\n내용이 길게 이어지다 잘림'
    out = S._extract_json(raw)
    assert out["title"] == "회의"
    assert "개요" in out["summary_md"]
    assert "\n" in out["summary_md"]  # \\n 이 실제 개행으로 복원


def test_extract_json_no_brace_raises():
    with pytest.raises(ValueError):
        S._extract_json("그냥 평범한 텍스트, JSON 아님")


# ── _parse_summary_response / chunk ──────────────────────────
def test_parse_summary_valid():
    md = "## A\n" + "가" * 60 + "\n## B\n" + "나" * 60
    raw = json.dumps({"title": "제목", "summary_md": md}, ensure_ascii=False)
    out = S._parse_summary_response(raw, required_headings=("## A", "## B"), min_summary_chars=50)
    assert out["title"] == "제목"
    assert "## A" in out["summary_md"]


def test_parse_summary_missing_heading():
    raw = json.dumps({"title": "T", "summary_md": "## A\n내용"}, ensure_ascii=False)
    with pytest.raises(S.SummaryParseError):
        S._parse_summary_response(raw, required_headings=("## A", "## 없는섹션"), min_summary_chars=0)


def test_parse_summary_too_short():
    raw = json.dumps({"title": "T", "summary_md": "짧음"}, ensure_ascii=False)
    with pytest.raises(S.SummaryParseError):
        S._parse_summary_response(raw, required_headings=None, min_summary_chars=1000)


def test_parse_summary_not_json():
    with pytest.raises(S.SummaryParseError):
        S._parse_summary_response("JSON 아님", required_headings=None, min_summary_chars=0)


def test_parse_chunk_response_relaxed():
    # chunk는 헤딩 검증 없음, 짧은 임계값
    raw = json.dumps({"title": "구간", "summary_md": "내" * 800}, ensure_ascii=False)
    out = S._parse_chunk_response(raw, min_summary_chars=700)
    assert out["title"] == "구간"


def test_safe_title_from_raw():
    assert S._safe_title_from_raw('{"title":"좋은제목","summary_md":"x"}') == "좋은제목"
    assert S._safe_title_from_raw("깨진 응답") == "회의록"


def test_title_from_chunk_summaries_picks_non_generic():
    assert S._title_from_chunk_summaries([{"title": "회의록"}, {"title": "산업안전 회의"}]) == "산업안전 회의"
    assert S._title_from_chunk_summaries([{"title": "회의록"}]) == "회의록"


# ── 토큰/컨텍스트 추정 ────────────────────────────────────────
def test_estimate_transcript_tokens():
    assert S._estimate_transcript_tokens("") == 2048
    assert S._estimate_transcript_tokens("a" * 1000) == 2548


def test_recommended_context_rounding_and_clamps():
    assert S._recommended_context(5000) == 5120     # 1024 배수로 올림
    assert S._recommended_context(100) == 4096       # 최소
    assert S._recommended_context(10 ** 9) == 131072  # 최대 클램프


def test_ensure_context_fits():
    S._ensure_context_fits("짧은 회의 내용", max_ctx=32768)  # 예외 없음
    big = "가" * 200_000  # ≈ 102,048 토큰
    with pytest.raises(S.SummaryContextError) as ei:
        S._ensure_context_fits(big, max_ctx=8192)
    assert ei.value.recommended_ctx > 8192


# ── 청킹 ─────────────────────────────────────────────────────
def test_split_empty_and_disabled():
    assert S._split_utterances_for_summary([]) == []
    utts = [{"start": 0, "end": 5, "text": "a", "speaker": "s"}]
    assert S._split_utterances_for_summary(utts, chunk_sec=0) == [utts]


def test_split_by_time():
    utts = [
        {"start": 0, "end": 4, "text": "a", "speaker": "s"},
        {"start": 4, "end": 8, "text": "b", "speaker": "s"},
        {"start": 8, "end": 20, "text": "c", "speaker": "s"},  # elapsed 20 ≥ 10 → 분할
    ]
    chunks = S._split_utterances_for_summary(utts, chunk_sec=10, max_ctx=32768)
    assert len(chunks) == 2
    assert [u["text"] for u in chunks[0]] == ["a", "b"]
    assert [u["text"] for u in chunks[1]] == ["c"]
