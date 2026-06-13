"""구간/섹션/최종 요약 오케스트레이션 + summarize() 진입점."""
from __future__ import annotations

import json

from .prompts import CHUNK_SYSTEM_PROMPT, FINAL_SECTION_SPECS, SYSTEM_PROMPT
from .parsing import (
    SummaryParseError,
    _parse_chunk_response,
    _parse_section_response,
    _parse_summary_response,
    _safe_title_from_raw,
    _title_from_chunk_summaries,
)
from .chunking import (
    _build_ollama_options,
    _chunk_min_summary_chars,
    _ensure_context_fits,
    _final_min_summary_chars,
    _fmt_time,
    _format_transcript,
    _section_min_summary_chars,
    _split_utterances_for_summary,
    _utterance_bounds,
)
from .ollama_io import _chat_json_with_retries


def _summarize_chunk(
    client,
    chunk: list[dict],
    *,
    chunk_index: int,
    total_chunks: int,
    model: str,
    max_ctx: int,
    num_predict: int,
    num_gpu: int | None,
    keep_alive: str,
    max_retries: int,
) -> dict:
    transcript = _format_transcript(chunk, include_time=True)
    _ensure_context_fits(transcript, max_ctx=max_ctx)
    min_chars = _chunk_min_summary_chars(transcript)
    start, end = _utterance_bounds(chunk)
    time_range = f"{_fmt_time(start)}-{_fmt_time(end)}"
    user_msg = (
        f"다음은 긴 회의 중 {chunk_index}/{total_chunks} 구간({time_range})입니다. "
        "최종 회의록의 재료가 되도록 이 구간에서 나온 모든 중요한 사례, 숫자, 기관명, "
        "정책명, 질의응답, 결정/검토/후속 조치를 상세히 정리하세요. "
        "반드시 JSON만 출력하세요.\n\n"
        f"--- 구간 transcript 시작 ---\n{transcript}\n--- 구간 transcript 끝 ---"
    )
    options = _build_ollama_options(
        transcript,
        max_ctx=max_ctx,
        num_predict=max(4096, min(num_predict, 8192)),
        num_gpu=num_gpu,
    )
    try:
        parsed = _chat_json_with_retries(
            client,
            model=model,
            messages=[
                {"role": "system", "content": CHUNK_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            options=options,
            keep_alive=keep_alive,
            max_retries=max_retries,
            parser=lambda raw: _parse_chunk_response(raw, min_summary_chars=min_chars),
            label=f"구간 {chunk_index}/{total_chunks}",
        )
    except (SummaryParseError, RuntimeError) as e:
        parsed = _fallback_chunk_summary(
            chunk,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            time_range=time_range,
            reason=str(e),
        )
    return {
        "index": chunk_index,
        "time_range": time_range,
        "title": parsed["title"],
        "summary_md": parsed["summary_md"],
    }


def _fallback_chunk_summary(
    chunk: list[dict],
    *,
    chunk_index: int,
    total_chunks: int,
    time_range: str,
    reason: str,
) -> dict:
    import sys

    sys.stdout.write(
        f"    구간 {chunk_index}/{total_chunks} 요약이 불안정해서 원문 발화를 최종 재료로 보존합니다. "
        f"({reason[:120]})\n"
    )
    sys.stdout.flush()

    transcript = _format_transcript(chunk, include_time=True)
    summary_md = (
        "## 구간 개요\n"
        f"- 이 구간({time_range})은 Ollama 구간 요약이 충분하지 않아 원문 발화를 최종 통합 재료로 보존했습니다.\n"
        "- 아래 발화 목록을 기준으로 최종 회의록에서 논의 흐름, 결정 사항, 후속 조치를 판단해야 합니다.\n\n"
        "## 핵심 발언과 근거\n"
        f"{transcript}\n\n"
        "## 결정·검토·후속 조치 후보\n"
        "- 이 구간의 결정/후속 조치는 위 원문 발화를 바탕으로 최종 통합 단계에서 추출합니다."
    )
    return {
        "title": f"구간 {chunk_index} 원문 발화 보존",
        "summary_md": summary_md,
    }


def _format_chunk_summaries(chunk_summaries: list[dict]) -> str:
    parts = []
    for chunk in chunk_summaries:
        parts.append(
            f"### 구간 {chunk['index']} ({chunk['time_range']}) - {chunk['title']}\n"
            f"{chunk['summary_md']}"
        )
    return "\n\n".join(parts)


def _summarize_final_section(
    client,
    material: str,
    *,
    heading: str,
    instructions: str,
    min_summary_chars: int,
    material_label: str = "구간별 상세 요약",
    model: str,
    max_ctx: int,
    num_predict: int,
    num_gpu: int | None,
    keep_alive: str,
    max_retries: int,
) -> str:
    user_msg = (
        f"아래 {material_label}을 바탕으로 최종 회의록의 `{heading}` 섹션만 작성하세요.\n"
        f"{instructions}\n"
        "반드시 JSON 객체 하나만 출력하세요. 스키마는 {\"summary_md\": \"...\"} 입니다. "
        f"summary_md는 반드시 `{heading}` 헤더로 시작해야 합니다.\n\n"
        f"--- {material_label} 시작 ---\n{material}\n--- {material_label} 끝 ---"
    )
    section_predict = max(2048, min(num_predict, 4096))
    if heading in {"## 주요 논의 사항", "## 액션 아이템"}:
        section_predict = max(4096, min(num_predict, 8192))
    options = _build_ollama_options(
        material,
        max_ctx=max_ctx,
        num_predict=section_predict,
        num_gpu=num_gpu,
    )
    parsed = _chat_json_with_retries(
        client,
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 한국어 회의록 편집자입니다. 요청받은 단일 섹션만 "
                    "풍부하고 구체적으로 작성하고, JSON 외 텍스트를 출력하지 않습니다."
                ),
            },
            {"role": "user", "content": user_msg},
        ],
        options=options,
        keep_alive=keep_alive,
        max_retries=max_retries,
        parser=lambda raw: _parse_section_response(
            raw,
            heading=heading,
            min_summary_chars=min_summary_chars,
        ),
        label=f"섹션 보강 {heading}",
    )
    return parsed["summary_md"]


def _summarize_sections_from_chunks(
    client,
    material: str,
    utterances: list[dict],
    *,
    previous_raw: str,
    fallback_title: str,
    material_label: str = "구간별 상세 요약",
    notice: str = "최종 통합 요약이 필수 섹션을 놓쳐서 섹션별 보강 요약으로 전환합니다.",
    model: str,
    max_ctx: int,
    num_predict: int,
    num_gpu: int | None,
    keep_alive: str,
    max_retries: int,
) -> dict:
    import sys

    title = _safe_title_from_raw(previous_raw)
    if title == "회의록" and fallback_title:
        title = fallback_title
    sys.stdout.write(f"    {notice}\n")
    sys.stdout.flush()

    sections = []
    for heading, instructions, min_chars in FINAL_SECTION_SPECS:
        effective_min_chars = _section_min_summary_chars(utterances, heading, min_chars)
        sections.append(
            _summarize_final_section(
                client,
                material,
                heading=heading,
                instructions=instructions,
                min_summary_chars=effective_min_chars,
                material_label=material_label,
                model=model,
                max_ctx=max_ctx,
                num_predict=num_predict,
                num_gpu=num_gpu,
                keep_alive=keep_alive,
                max_retries=max_retries,
            )
        )

    summary_md = "\n\n".join(sections)
    return _parse_summary_response(
        json.dumps({"title": title, "summary_md": summary_md}, ensure_ascii=False),
        min_summary_chars=_final_min_summary_chars(utterances),
    )


def _summarize_from_chunks(
    client,
    chunk_summaries: list[dict],
    utterances: list[dict],
    *,
    model: str,
    max_ctx: int,
    num_predict: int,
    num_gpu: int | None,
    keep_alive: str,
    max_retries: int,
) -> dict:
    material = _format_chunk_summaries(chunk_summaries)
    _ensure_context_fits(material, max_ctx=max_ctx)
    user_msg = (
        "아래 구간별 상세 요약들을 하나의 최종 회의록으로 통합하세요. "
        "구간별 내용을 빠뜨리지 말고 중복은 정리하되, 사례·숫자·기관명·정책명·발언자 메시지·"
        "결정 사항·액션 아이템은 실제로 언급된 경우에만 보존하세요. "
        "없는 결정/액션을 만들지 마세요. "
        "반드시 {\"title\": \"...\", \"summary_md\": \"...\"} JSON만 출력하세요.\n\n"
        f"--- 구간별 상세 요약 시작 ---\n{material}\n--- 구간별 상세 요약 끝 ---"
    )
    options = _build_ollama_options(
        material,
        max_ctx=max_ctx,
        num_predict=num_predict,
        num_gpu=num_gpu,
    )
    min_chars = _final_min_summary_chars(utterances)
    try:
        return _chat_json_with_retries(
            client,
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            options=options,
            keep_alive=keep_alive,
            max_retries=max_retries,
            parser=lambda raw: _parse_summary_response(raw, min_summary_chars=min_chars),
            label="최종 통합 요약",
        )
    except SummaryParseError as e:
        return _summarize_sections_from_chunks(
            client,
            material,
            utterances,
            previous_raw=e.raw,
            fallback_title=_title_from_chunk_summaries(chunk_summaries),
            model=model,
            max_ctx=max_ctx,
            num_predict=num_predict,
            num_gpu=num_gpu,
            keep_alive=keep_alive,
            max_retries=max_retries,
        )


def summarize(
    utterances: list[dict],
    *,
    source_context: str = "",
    model: str = "gemma4:e2b",
    host: str = "http://127.0.0.1:11434",
    timeout: float = 300.0,
    keep_alive: str = "0",
    max_retries: int = 2,
    max_ctx: int = 32768,
    num_predict: int = 8192,
    num_gpu: int | None = None,
    chunk_sec: int = 900,
) -> dict:
    """발화 리스트를 받아 {title, summary_md} 반환."""
    try:
        from ollama import Client
    except ImportError as e:
        raise RuntimeError("ollama 패키지가 필요합니다: pip install ollama") from e

    if not utterances:
        return {"title": "(빈 회의)", "summary_md": "_발화 내용이 없습니다._"}

    client = Client(host=host, timeout=timeout)
    chunks = _split_utterances_for_summary(utterances, chunk_sec=chunk_sec, max_ctx=max_ctx)
    if len(chunks) >= 2:
        import sys

        start, end = _utterance_bounds(utterances)
        sys.stdout.write(
            f"    긴 회의 분할 요약 사용: {len(chunks)}개 구간 "
            f"({_fmt_time(start)}-{_fmt_time(end)}, 구간 목표 {chunk_sec}s)\n"
        )
        sys.stdout.flush()
        chunk_summaries = []
        for idx, chunk in enumerate(chunks, start=1):
            c_start, c_end = _utterance_bounds(chunk)
            sys.stdout.write(
                f"    [{idx}/{len(chunks)}] 구간 요약 "
                f"({_fmt_time(c_start)}-{_fmt_time(c_end)}, 발화 {len(chunk)}건)\n"
            )
            sys.stdout.flush()
            chunk_summaries.append(
                _summarize_chunk(
                    client,
                    chunk,
                    chunk_index=idx,
                    total_chunks=len(chunks),
                    model=model,
                    max_ctx=max_ctx,
                    num_predict=num_predict,
                    num_gpu=num_gpu,
                    keep_alive=keep_alive,
                    max_retries=max_retries,
                )
            )
        sys.stdout.write("    구간 요약 완료 - 최종 회의록 통합 중...\n")
        sys.stdout.flush()
        return _summarize_from_chunks(
            client,
            chunk_summaries,
            utterances,
            model=model,
            max_ctx=max_ctx,
            num_predict=num_predict,
            num_gpu=num_gpu,
            keep_alive=keep_alive,
            max_retries=max_retries,
        )

    transcript = _format_transcript(utterances, include_time=True)
    _ensure_context_fits(transcript, max_ctx=max_ctx)

    source_note = f"입력 파일명/회의 힌트: {source_context}\n\n" if source_context else ""
    user_msg = (
        "다음 회의 대화를 **풍성하고 구체적으로** 정리해 주십시오. "
        "각 섹션은 짧게 끝내지 말고 충실히 채우고, 회의에서 언급된 모든 안건/상황/인물/숫자를 빠짐없이 포함하세요. "
        "단, 결정 사항과 액션 아이템은 실제로 언급된 경우에만 작성하고 억지로 만들지 마십시오. "
        "**반드시 {\"title\": \"...\", \"summary_md\": \"...\"} 형태의 JSON만 출력**. "
        "JSON 외 다른 텍스트 일절 금지. 응답 첫 글자는 반드시 `{`여야 하며, "
        "`##` 같은 마크다운 헤더로 시작하면 안 됩니다.\n\n"
        f"{source_note}"
        f"--- 회의 대화 시작 ---\n{transcript}\n--- 회의 대화 끝 ---"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    options = _build_ollama_options(
        transcript,
        max_ctx=max_ctx,
        num_predict=num_predict,
        num_gpu=num_gpu,
    )

    try:
        return _chat_json_with_retries(
            client,
            model=model,
            messages=messages,
            options=options,
            keep_alive=keep_alive,
            max_retries=max_retries,
            parser=lambda raw: _parse_summary_response(
                raw,
                min_summary_chars=_final_min_summary_chars(utterances),
            ),
            label="요약",
        )
    except SummaryParseError as e:
        return _summarize_sections_from_chunks(
            client,
            transcript,
            utterances,
            previous_raw=e.raw,
            fallback_title=_safe_title_from_raw(e.raw),
            material_label="원본 transcript",
            notice="요약이 필수 섹션을 놓쳐서 섹션별 보강 요약으로 전환합니다.",
            model=model,
            max_ctx=max_ctx,
            num_predict=num_predict,
            num_gpu=num_gpu,
            keep_alive=keep_alive,
            max_retries=max_retries,
        )
