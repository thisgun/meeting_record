"""transcript 포맷·토큰/컨텍스트 추정·구간 분할 (Ollama 호출 없음, 순수 로직)."""
from __future__ import annotations


class SummaryContextError(RuntimeError):
    """Raised when the transcript is larger than the configured Ollama context."""

    def __init__(self, message: str, *, approx_tokens: int, max_ctx: int, recommended_ctx: int):
        super().__init__(message)
        self.approx_tokens = approx_tokens
        self.max_ctx = max_ctx
        self.recommended_ctx = recommended_ctx


def _fmt_time(sec: float) -> str:
    total = max(0, int(float(sec or 0.0)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _format_transcript(utterances: list[dict], *, include_time: bool = False) -> str:
    lines = []
    for u in utterances:
        speaker = u.get("speaker", "?")
        text = (u.get("text") or "").strip()
        if text:
            if include_time:
                start = _fmt_time(float(u.get("start", 0.0)))
                end = _fmt_time(float(u.get("end", u.get("start", 0.0))))
                lines.append(f"[{start}-{end}] {speaker}: {text}")
            else:
                lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _build_ollama_options(
    transcript: str,
    *,
    max_ctx: int = 32768,
    num_predict: int = 8192,
    num_gpu: int | None = None,
    chunk_sec: int = 900,
) -> dict:
    """Build memory-aware Ollama options from transcript length."""
    max_ctx = max(4096, int(max_ctx))
    num_predict = max(1024, int(num_predict))

    # 긴 회의 대비: context window를 토큰 추정치에 따라 동적 설정
    # 한국어는 평균 ~2.5자/토큰 → transcript 문자수 × 0.4 토큰 추정 + 여유
    approx_tokens = int(len(transcript) * 0.5) + 2048
    num_ctx = min(max_ctx, max(4096, ((approx_tokens // 1024) + 1) * 1024))

    options = {
        "temperature": 0.2,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
    }
    if num_gpu is not None:
        options["num_gpu"] = int(num_gpu)
    return options


def _estimate_transcript_tokens(transcript: str) -> int:
    """Rough token estimate for Korean transcript budgeting."""
    return int(len(transcript) * 0.5) + 2048


def _recommended_context(approx_tokens: int) -> int:
    return min(131072, max(4096, ((approx_tokens // 1024) + 1) * 1024))


def _ensure_context_fits(transcript: str, *, max_ctx: int) -> None:
    approx_tokens = _estimate_transcript_tokens(transcript)
    recommended = _recommended_context(approx_tokens)
    if approx_tokens <= max_ctx:
        return
    raise SummaryContextError(
        "회의 transcript가 현재 Ollama context보다 큽니다. "
        f"추정 입력 {approx_tokens}토큰, 현재 OLLAMA_NUM_CTX_MAX={max_ctx}, "
        f"권장 {recommended} 이상입니다. .env에서 OLLAMA_NUM_CTX_MAX={recommended}로 "
        "올린 뒤 다시 실행하세요. STT 캐시가 있으면 요약 단계부터 이어집니다.",
        approx_tokens=approx_tokens,
        max_ctx=max_ctx,
        recommended_ctx=recommended,
    )


def _utterance_bounds(utterances: list[dict]) -> tuple[float, float]:
    starts = [float(u.get("start", 0.0)) for u in utterances if (u.get("text") or "").strip()]
    ends = [float(u.get("end", u.get("start", 0.0))) for u in utterances if (u.get("text") or "").strip()]
    if not starts or not ends:
        return 0.0, 0.0
    return min(starts), max(ends)


def _final_min_summary_chars(utterances: list[dict]) -> int:
    start, end = _utterance_bounds(utterances)
    duration = max(0.0, end - start)
    if duration >= 5400:
        return 3000
    if duration >= 1800:
        return 2000
    return 800


def _section_min_summary_chars(utterances: list[dict], heading: str, default: int) -> int:
    start, end = _utterance_bounds(utterances)
    duration = max(0.0, end - start)
    if duration < 900:
        caps = {
            "## 회의 개요": 220,
            "## 회의 흐름 (시간대별)": 220,
            "## 주요 논의 사항": 450,
            "## 발언자별 핵심 메시지": 180,
            "## 결정 사항": 160,
            "## 액션 아이템": 160,
        }
        return min(default, caps.get(heading, default))
    if duration < 1800:
        caps = {
            "## 회의 개요": 300,
            "## 회의 흐름 (시간대별)": 350,
            "## 주요 논의 사항": 700,
            "## 발언자별 핵심 메시지": 250,
            "## 결정 사항": 220,
            "## 액션 아이템": 220,
        }
        return min(default, caps.get(heading, default))
    return default


def _max_chunk_input_tokens(max_ctx: int) -> int:
    return max(4096, min(12000, max(4096, int(max_ctx) - 2048)))


def _chunk_min_summary_chars(transcript: str) -> int:
    return min(600, max(250, len(transcript) // 3))


def _split_utterances_for_summary(
    utterances: list[dict],
    *,
    chunk_sec: int = 900,
    max_ctx: int = 32768,
) -> list[list[dict]]:
    """Split utterances into time/token bounded chunks for better long-meeting summaries."""
    clean = [u for u in utterances if (u.get("text") or "").strip()]
    if not clean or chunk_sec <= 0:
        return [clean] if clean else []

    max_tokens = _max_chunk_input_tokens(max_ctx)
    chunks: list[list[dict]] = []
    current: list[dict] = []
    chunk_start: float | None = None

    for utterance in clean:
        start = float(utterance.get("start", 0.0))
        end = float(utterance.get("end", start))
        if chunk_start is None:
            chunk_start = start

        candidate = current + [utterance]
        candidate_text = _format_transcript(candidate, include_time=True)
        candidate_tokens = _estimate_transcript_tokens(candidate_text)
        elapsed = end - chunk_start
        should_split = bool(current) and (elapsed >= chunk_sec or candidate_tokens > max_tokens)
        if should_split:
            chunks.append(current)
            current = [utterance]
            chunk_start = start
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks
