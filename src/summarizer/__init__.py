"""Ollama 기반 회의 요약 패키지.

986줄 단일 모듈을 역할별로 분리:
- prompts:   시스템 프롬프트/섹션 스키마 상수
- parsing:   LLM 응답 JSON 추출·검증 (순수)
- chunking:  transcript 포맷·토큰/컨텍스트 추정·구간 분할 (순수)
- ollama_io: Ollama 스트리밍 호출 + 재시도
- sections:  구간/섹션/최종 요약 오케스트레이션 + summarize()

기존 코드 호환: `from src import summarizer` 후 `summarizer.summarize(...)`,
`summarizer.SummaryContextError`, 그리고 (테스트용) 내부 함수 접근이 그대로 동작하도록 재노출한다.
"""
from __future__ import annotations

from .prompts import (
    CHUNK_SYSTEM_PROMPT,
    FINAL_SECTION_SPECS,
    REQUIRED_SUMMARY_HEADINGS,
    SYSTEM_PROMPT,
)
from .parsing import (
    SummaryParseError,
    _extract_json,
    _parse_chunk_response,
    _parse_section_response,
    _parse_summary_response,
    _safe_title_from_raw,
    _title_from_chunk_summaries,
)
from .chunking import (
    SummaryContextError,
    _build_ollama_options,
    _chunk_min_summary_chars,
    _ensure_context_fits,
    _estimate_transcript_tokens,
    _final_min_summary_chars,
    _fmt_time,
    _format_transcript,
    _max_chunk_input_tokens,
    _recommended_context,
    _section_min_summary_chars,
    _split_utterances_for_summary,
    _utterance_bounds,
)
from .ollama_io import _chat_json_with_retries, _stream_chat
from .sections import (
    _fallback_chunk_summary,
    _format_chunk_summaries,
    _summarize_chunk,
    _summarize_final_section,
    _summarize_from_chunks,
    _summarize_sections_from_chunks,
    summarize,
)

__all__ = [
    "summarize",
    "SummaryParseError",
    "SummaryContextError",
    "SYSTEM_PROMPT",
    "CHUNK_SYSTEM_PROMPT",
    "REQUIRED_SUMMARY_HEADINGS",
    "FINAL_SECTION_SPECS",
]
