"""LLM 요약 응답에서 JSON 추출·검증 (Ollama 호출 없음, 순수 로직)."""
from __future__ import annotations

import json
import re

from .prompts import REQUIRED_SUMMARY_HEADINGS


class SummaryParseError(RuntimeError):
    """Raised when Ollama returns a non-JSON or unusable summary."""

    def __init__(self, message: str, *, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def _extract_json(raw: str) -> dict:
    """LLM 응답에서 JSON 객체만 추출. 잘림 보정 포함."""
    raw = raw.strip()
    # 코드펜스 제거
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    start = raw.find("{")
    if start == -1:
        raise ValueError(f"JSON 시작 { '{' } 못 찾음:\n{raw[:500]}")
    end = raw.rfind("}")

    # 1) 정상 종료된 JSON 시도
    if end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 2) 잘림 보정: title과 summary_md를 정규식으로 추출
    # Section-only fallback responses may contain just {"summary_md": "..."}
    # and can be truncated before the closing quote/brace.
    title_m = re.search(r'"title"\s*:\s*"([^"]*)"', raw)
    md_m = re.search(r'"summary_md"\s*:\s*"(.*)', raw, re.DOTALL)
    if not md_m:
        raise ValueError(f"부분 추출 실패. raw 앞 500자:\n{raw[:500]}")

    md = md_m.group(1).rstrip()
    # 마지막 닫는 따옴표/중괄호가 잘린 상태일 수 있음 → JSON 꼬리 제거
    if md.endswith('"}'):
        md = md[:-2]
    elif md.endswith('"'):
        md = md[:-1]
    # JSON escape 풀기
    md = md.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    title = title_m.group(1).strip() if title_m else ""
    return {"title": title, "summary_md": md.strip()}


def _parse_summary_response(
    raw: str,
    *,
    required_headings: list[str] | tuple[str, ...] | None = REQUIRED_SUMMARY_HEADINGS,
    min_summary_chars: int = 2000,
) -> dict:
    """Parse and validate the JSON summary returned by Ollama."""
    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        preview = raw.strip()[:200]
        raise SummaryParseError(
            f"요약 응답이 JSON이 아닙니다: {e}. 원본 앞부분: {preview!r}",
            raw=raw,
        ) from e

    title = str(data.get("title") or "회의록").strip()[:200]
    summary_md = str(data.get("summary_md") or "").strip()
    if not summary_md:
        raise SummaryParseError("요약 JSON에 summary_md 내용이 없습니다.", raw=raw)
    if required_headings:
        missing = [heading for heading in required_headings if heading not in summary_md]
    else:
        missing = []
    if missing:
        raise SummaryParseError(
            "요약 본문에 필수 섹션이 누락되었습니다: " + ", ".join(missing),
            raw=raw,
        )
    if min_summary_chars > 0 and len(summary_md) < min_summary_chars:
        raise SummaryParseError(
            f"요약 본문이 너무 짧습니다 ({len(summary_md)}자). 더 상세한 요약이 필요합니다.",
            raw=raw,
        )
    return {"title": title, "summary_md": summary_md}


def _parse_chunk_response(raw: str, *, min_summary_chars: int = 700) -> dict:
    return _parse_summary_response(
        raw,
        # Chunk summaries are intermediate material. The final integrated
        # meeting note keeps strict section validation, but chunk headings may
        # vary slightly depending on the model response.
        required_headings=None,
        min_summary_chars=min_summary_chars,
    )


def _parse_section_response(raw: str, *, heading: str, min_summary_chars: int) -> dict:
    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise SummaryParseError(f"{heading} 응답이 JSON이 아닙니다: {e}", raw=raw) from e

    summary_md = str(data.get("summary_md") or "").strip()
    if not summary_md:
        raise SummaryParseError(f"{heading} 응답에 summary_md가 없습니다.", raw=raw)
    if heading not in summary_md:
        summary_md = f"{heading}\n{summary_md}"
    if len(summary_md) < min_summary_chars:
        raise SummaryParseError(
            f"{heading} 내용이 너무 짧습니다 ({len(summary_md)}자).",
            raw=raw,
        )
    return {"summary_md": summary_md}


def _safe_title_from_raw(raw: str) -> str:
    try:
        data = _extract_json(raw)
    except Exception:
        return "회의록"
    title = str(data.get("title") or "").strip()
    return title[:200] or "회의록"


def _title_from_chunk_summaries(chunk_summaries: list[dict]) -> str:
    generic = {"회의록", "구간 요약", "회의 요약"}
    for chunk in chunk_summaries:
        title = str(chunk.get("title") or "").strip()
        if title and title not in generic:
            return title[:200]
    return "회의록"
