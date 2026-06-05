import inspect
import json

import pytest

from src.summarizer import (
    SummaryContextError,
    SummaryParseError,
    _build_ollama_options,
    _chunk_min_summary_chars,
    _ensure_context_fits,
    _parse_chunk_response,
    _parse_section_response,
    _parse_summary_response,
    _split_utterances_for_summary,
    _title_from_chunk_summaries,
    summarize,
)


def test_ollama_options_cap_context_for_low_memory() -> None:
    transcript = "회의 내용 " * 10000

    options = _build_ollama_options(
        transcript,
        max_ctx=8192,
        num_predict=4096,
        num_gpu=0,
    )

    assert options["num_ctx"] == 8192
    assert options["num_predict"] == 4096
    assert options["num_gpu"] == 0


def test_ollama_options_omit_num_gpu_when_auto() -> None:
    options = _build_ollama_options("짧은 회의", num_gpu=None)

    assert options["num_ctx"] == 4096
    assert "num_gpu" not in options


def test_summarize_default_timeout_bounds_zombie_wait() -> None:
    signature = inspect.signature(summarize)

    assert signature.parameters["timeout"].default == 300.0
    assert signature.parameters["chunk_sec"].default == 900


def test_parse_summary_rejects_markdown_only_response() -> None:
    with pytest.raises(SummaryParseError):
        _parse_summary_response("##")


def test_parse_summary_accepts_valid_json() -> None:
    summary_md = "\n".join(
        [
            "## 회의 개요",
            "- " + ("회의 배경과 목적을 상세히 설명합니다. " * 20),
            "## 회의 흐름 (시간대별)",
            "- " + ("초반부터 후반까지 흐름을 설명합니다. " * 20),
            "## 주요 논의 사항",
            "### 1. 주요 안건",
            "- " + ("핵심 논의와 사례를 충분히 정리합니다. " * 20),
            "## 발언자별 핵심 메시지",
            "- " + ("발언자별 메시지를 구체적으로 정리합니다. " * 20),
            "## 결정 사항",
            "- " + ("결정된 내용과 후속 방향을 정리합니다. " * 20),
            "## 액션 아이템",
            "- [ ] " + ("담당자와 할 일을 구체적으로 정리합니다. " * 20),
        ]
    )
    parsed = _parse_summary_response(
        json.dumps({"title": "회의", "summary_md": summary_md}, ensure_ascii=False)
    )

    assert parsed["title"] == "회의"
    assert parsed["summary_md"].startswith("## 회의 개요")


def test_parse_summary_rejects_incomplete_short_summary() -> None:
    raw = '{"title": "회의", "summary_md": "## 회의 개요\\n- 짧은 내용"}'

    with pytest.raises(SummaryParseError):
        _parse_summary_response(raw)


def test_context_guard_rejects_transcript_larger_than_max_ctx() -> None:
    transcript = "긴 회의 내용 " * 4000

    with pytest.raises(SummaryContextError) as exc:
        _ensure_context_fits(transcript, max_ctx=8192)

    assert exc.value.recommended_ctx > 8192


def test_split_utterances_for_summary_uses_time_chunks() -> None:
    utterances = [
        {"start": 0, "end": 10, "speaker": "사용자1", "text": "첫 번째 발화"},
        {"start": 500, "end": 510, "speaker": "사용자1", "text": "두 번째 발화"},
        {"start": 950, "end": 960, "speaker": "사용자2", "text": "세 번째 발화"},
        {"start": 1300, "end": 1310, "speaker": "사용자2", "text": "네 번째 발화"},
    ]

    chunks = _split_utterances_for_summary(utterances, chunk_sec=900, max_ctx=32768)

    assert [len(chunk) for chunk in chunks] == [2, 2]


def test_chunk_summary_min_chars_adapts_to_short_tail_chunk() -> None:
    assert _chunk_min_summary_chars("짧은 마지막 발화" * 10) == 250
    assert _chunk_min_summary_chars("긴 구간 발화" * 1000) == 700


def test_parse_chunk_response_allows_heading_variation() -> None:
    summary_md = "## 구간 핵심\n- " + ("구간 재료를 충분히 자세하게 정리합니다. " * 30)
    parsed = _parse_chunk_response(
        json.dumps({"title": "구간 요약", "summary_md": summary_md}, ensure_ascii=False),
        min_summary_chars=250,
    )

    assert parsed["title"] == "구간 요약"


def test_parse_section_response_prefixes_missing_heading() -> None:
    parsed = _parse_section_response(
        json.dumps(
            {"summary_md": "- " + ("후속 조치를 구체적으로 정리합니다. " * 20)},
            ensure_ascii=False,
        ),
        heading="## 액션 아이템",
        min_summary_chars=100,
    )

    assert parsed["summary_md"].startswith("## 액션 아이템")


def test_title_from_chunk_summaries_uses_first_specific_title() -> None:
    title = _title_from_chunk_summaries(
        [
            {"title": "구간 요약"},
            {"title": "산업안전 강화와 중대재해 감축 방안"},
        ]
    )

    assert title == "산업안전 강화와 중대재해 감축 방안"
