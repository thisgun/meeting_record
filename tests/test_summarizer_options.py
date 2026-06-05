import inspect
import json
import sys
import types

import pytest

from src import summarizer as summarizer_module
from src.summarizer import (
    SummaryContextError,
    SummaryParseError,
    _build_ollama_options,
    _chunk_min_summary_chars,
    _ensure_context_fits,
    _parse_chunk_response,
    _parse_section_response,
    _parse_summary_response,
    _section_min_summary_chars,
    _split_utterances_for_summary,
    _summarize_chunk,
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
    assert _chunk_min_summary_chars("긴 구간 발화" * 1000) == 600


def test_section_min_chars_relaxes_for_short_meetings() -> None:
    short = [{"start": 0, "end": 600, "speaker": "사용자1", "text": "짧은 회의"}]
    long = [{"start": 0, "end": 7200, "speaker": "사용자1", "text": "긴 회의"}]

    assert _section_min_summary_chars(short, "## 액션 아이템", 400) == 160
    assert _section_min_summary_chars(short, "## 주요 논의 사항", 900) == 450
    assert _section_min_summary_chars(long, "## 액션 아이템", 400) == 400


def test_parse_chunk_response_allows_heading_variation() -> None:
    summary_md = "## 구간 핵심\n- " + ("구간 재료를 충분히 자세하게 정리합니다. " * 30)
    parsed = _parse_chunk_response(
        json.dumps({"title": "구간 요약", "summary_md": summary_md}, ensure_ascii=False),
        min_summary_chars=250,
    )

    assert parsed["title"] == "구간 요약"


def test_parse_chunk_response_accepts_six_hundred_char_intermediate_summary() -> None:
    summary_md = "## 구간 개요\n- " + ("구간 핵심과 후속 논의를 보존합니다. " * 45)

    parsed = _parse_chunk_response(
        json.dumps({"title": "구간 요약", "summary_md": summary_md}, ensure_ascii=False),
        min_summary_chars=600,
    )

    assert len(parsed["summary_md"]) >= 600


def test_summarize_chunk_preserves_transcript_when_chunk_summary_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_chat_json_with_retries(*args, **kwargs):
        raise SummaryParseError("요약 본문이 너무 짧습니다", raw='{"summary_md": "짧음"}')

    monkeypatch.setattr(summarizer_module, "_chat_json_with_retries", fake_chat_json_with_retries)

    parsed = _summarize_chunk(
        object(),
        [
            {"start": 858, "end": 870, "speaker": "사용자1", "text": "사과를 먼저 해야 합니다."},
            {"start": 900, "end": 930, "speaker": "사용자2", "text": "동정심을 얻는 전략을 검토합시다."},
        ],
        chunk_index=2,
        total_chunks=2,
        model="gemma4:e2b",
        max_ctx=32768,
        num_predict=8192,
        num_gpu=None,
        keep_alive="0",
        max_retries=2,
    )

    assert parsed["title"] == "구간 2 원문 발화 보존"
    assert "사과를 먼저 해야 합니다." in parsed["summary_md"]
    assert "동정심을 얻는 전략" in parsed["summary_md"]


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


def test_parse_section_response_recovers_truncated_summary_only_json() -> None:
    raw = '{"summary_md": "## 주요 논의 사항\\n- ' + ("중요한 사례와 숫자를 자세히 보존합니다. " * 40)

    parsed = _parse_section_response(raw, heading="## 주요 논의 사항", min_summary_chars=200)

    assert parsed["summary_md"].startswith("## 주요 논의 사항")
    assert "중요한 사례" in parsed["summary_md"]


def test_title_from_chunk_summaries_uses_first_specific_title() -> None:
    title = _title_from_chunk_summaries(
        [
            {"title": "구간 요약"},
            {"title": "산업안전 강화와 중대재해 감축 방안"},
        ]
    )

    assert title == "산업안전 강화와 중대재해 감축 방안"


def test_summarize_single_pass_falls_back_to_section_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "ollama",
        types.SimpleNamespace(Client=lambda host, timeout: object()),
    )
    calls: list[str] = []

    def fake_chat_json_with_retries(*args, **kwargs):
        label = kwargs["label"]
        calls.append(label)
        if label == "요약":
            raise SummaryParseError(
                "missing sections",
                raw=json.dumps(
                    {
                        "title": "콘텐츠 회의",
                        "summary_md": "## 회의 개요\n- 일부 섹션만 생성됨",
                    },
                    ensure_ascii=False,
                ),
            )
        heading = label.replace("섹션 보강 ", "")
        return {"summary_md": heading + "\n- " + ("구체적인 내용을 충분히 정리합니다. " * 80)}

    monkeypatch.setattr(summarizer_module, "_chat_json_with_retries", fake_chat_json_with_retries)

    result = summarize(
        [
            {"start": 0, "end": 5, "speaker": "사용자1", "text": "이번 콘텐츠 방향을 논의합시다."},
            {"start": 6, "end": 12, "speaker": "사용자2", "text": "결정 사항과 후속 조치를 정리해야 합니다."},
        ]
    )

    assert calls[0] == "요약"
    assert "섹션 보강 ## 결정 사항" in calls
    assert "섹션 보강 ## 액션 아이템" in calls
    for heading in [
        "## 회의 개요",
        "## 회의 흐름 (시간대별)",
        "## 주요 논의 사항",
        "## 발언자별 핵심 메시지",
        "## 결정 사항",
        "## 액션 아이템",
    ]:
        assert heading in result["summary_md"]
