"""Ollama gemma4:e2b 기반 회의 요약."""
from __future__ import annotations

import json
import re


SYSTEM_PROMPT = """당신은 한국어 회의록 정리 전문가입니다. 회의 transcript에서 빠진 디테일 없이 풍부하고 구체적인 회의록을 작성합니다.

**출력 규칙 (절대 위반 금지):**
1. 응답은 **오직 하나의 JSON 객체**여야 합니다.
2. JSON 앞뒤에 어떠한 설명, 코드펜스(```), 추가 텍스트도 넣지 마십시오.
3. JSON 객체는 정확히 두 개의 키 `title`과 `summary_md`만 가집니다.
4. 응답 첫 글자는 반드시 `{`, 마지막 글자는 반드시 `}`여야 합니다.

**스키마:**
{
  "title": "회의 제목 (30자 이내, 핵심 주제)",
  "summary_md": "마크다운 본문 (아래 6개 섹션 모두 포함)"
}

**summary_md 본문 구조 (이 6개 섹션 헤더를 반드시 순서대로 사용):**

## 회의 개요
- 회의의 목적과 배경 1~2문장
- 주요 주제 2~3문장
- 회의 분위기나 톤 1문장
(총 4~6개 bullet)

## 회의 흐름 (시간대별)
- 시간대 또는 단계별로 회의가 어떻게 진행되었는지 5~8개 bullet
- 예: "(초반) 장관 모두 발언으로 산재 감축 의지 천명 → (중반) 지청별 사고 사례 발표 → (후반) 토론 및 마무리"

## 주요 논의 사항
각 주제를 헤더 (### 소제목)로 구분하고 그 아래 상세 bullet 4~7개씩.
주제는 transcript에 등장한 모든 핵심 안건을 빠짐없이 다룰 것 (보통 4~6개 주제).
구체적 숫자, 사례명, 부서명, 정책명, 인용을 적극 포함하세요.

## 발언자별 핵심 메시지
- **사용자2(추정 역할):** 주요 발언 요지 1~2문장
- **사용자3(추정 역할):** 주요 발언 요지 1~2문장
(각 화자별로. 노이즈성 사용자1은 생략)
실제 발화 흐름과 내용으로 화자의 역할 추정(예: 사회자/장관/발표자/임원 등)

## 결정 사항
- 합의되거나 결정된 내용을 구체적으로 5~8개 bullet
- 가능하면 누가/무엇을/언제 형식으로

## 액션 아이템
- [ ] 담당자/부서 | 구체적 할 일 | 기한(있다면)
- 최소 6~10개. transcript에서 "검토하겠다", "추진한다", "계속 노력하겠다" 등이 언급된 모든 후속 조치를 빠짐없이 적기.

**작성 원칙:**
1. **실제 transcript에 없는 정보는 추측하지 마십시오.** 없으면 "(언급 없음)"으로 표기.
2. **발화자 이름은 transcript에 나온 "사용자1", "사용자2" 그대로 사용.**
3. **일반론적 회의록 양식이 아니라 실제 대화 내용을 풍성하게 그대로 옮기십시오.**
4. **구체적인 숫자, 사례, 부서명, 정책명, 인물명을 인용하여 디테일이 살아있게 작성하십시오.**
5. **bullet은 짧은 단어가 아니라 1~3문장의 자세한 설명으로 작성하세요.**
6. **하나의 섹션도 빠뜨리지 말고 모두 채우세요.**
"""


REQUIRED_SUMMARY_HEADINGS = [
    "## 회의 개요",
    "## 회의 흐름 (시간대별)",
    "## 주요 논의 사항",
    "## 발언자별 핵심 메시지",
    "## 결정 사항",
    "## 액션 아이템",
]

CHUNK_SYSTEM_PROMPT = """당신은 한국어 회의록 보조 정리자입니다. 긴 회의를 구간별로 빠짐없이 정리합니다.

**출력 규칙:**
1. 응답은 오직 하나의 JSON 객체여야 합니다.
2. JSON 객체는 정확히 두 개의 키 `title`과 `summary_md`만 가집니다.
3. JSON 앞뒤 설명, 코드펜스, 추가 텍스트를 넣지 마십시오.

**summary_md 구조:**
## 구간 개요
- 이 구간에서 다룬 핵심 상황과 흐름

## 핵심 발언과 근거
- 발언자, 사례, 숫자, 정책명, 지역/기관명을 가능한 한 보존

## 결정·검토·후속 조치 후보
- 결정, 검토 약속, 지시, 후속 조치 가능성을 구체적으로 정리

**작성 원칙:**
- 원문에 없는 정보는 만들지 마십시오.
- 짧게 압축하지 말고 최종 회의록 재료가 되도록 풍부하게 정리하십시오.
- 노이즈성 발화도 왜 노이즈인지 구분할 수 있게 간단히 남기십시오.
"""


class SummaryParseError(RuntimeError):
    """Raised when Ollama returns a non-JSON or unusable summary."""

    def __init__(self, message: str, *, raw: str = ""):
        super().__init__(message)
        self.raw = raw


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
    title_m = re.search(r'"title"\s*:\s*"([^"]*)"', raw)
    md_m = re.search(r'"summary_md"\s*:\s*"(.*)', raw, re.DOTALL)
    if not (title_m and md_m):
        raise ValueError(f"부분 추출 실패. raw 앞 500자:\n{raw[:500]}")

    md = md_m.group(1).rstrip()
    # 마지막 닫는 따옴표가 잘린 상태일 수 있음 → 제거
    if md.endswith('"'):
        md = md[:-1]
    # JSON escape 풀기
    md = md.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    return {"title": title_m.group(1).strip(), "summary_md": md.strip()}


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
            f"요약 본문이 너무 짧습니다 ({len(summary_md)}자). 긴 회의는 상세 요약이 필요합니다.",
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


FINAL_SECTION_SPECS = [
    (
        "## 회의 개요",
        "회의의 목적, 배경, 주요 주제, 전반 분위기를 4~6개 bullet로 정리하세요.",
        350,
    ),
    (
        "## 회의 흐름 (시간대별)",
        "구간별 요약의 시간 흐름을 따라 초반, 중반, 후반 진행을 5~8개 bullet로 정리하세요.",
        500,
    ),
    (
        "## 주요 논의 사항",
        "핵심 안건을 4~6개 소제목으로 나누고 각 소제목마다 사례, 숫자, 기관명, 정책명을 보존하세요.",
        900,
    ),
    (
        "## 발언자별 핵심 메시지",
        "사용자별 발언 비중과 실제 발언 내용으로 역할을 추정하고 핵심 메시지를 정리하세요.",
        350,
    ),
    (
        "## 결정 사항",
        "합의, 지시, 검토하기로 한 내용, 정책 방향을 구체적으로 정리하세요. 명시적 결정이 없으면 그 한계를 적으세요.",
        350,
    ),
    (
        "## 액션 아이템",
        "후속 조치 후보를 체크박스 형식으로 정리하세요. 담당자/부서가 불명확하면 '담당 미정'으로 적으세요.",
        400,
    ),
]


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


def _max_chunk_input_tokens(max_ctx: int) -> int:
    return max(4096, min(12000, max(4096, int(max_ctx) - 2048)))


def _chunk_min_summary_chars(transcript: str) -> int:
    return min(700, max(250, len(transcript) // 2))


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


def _stream_chat(client, *, model, messages, options, format, keep_alive):
    """Ollama 스트리밍 1회 시도. (content, chunk_count, elapsed_sec) 반환.

    스트림 도중 RemoteProtocolError 등으로 끊기면 부분 content와 함께
    raise — 호출부에서 재시도 여부 결정.
    """
    import sys
    import time as _time

    sys.stdout.write(
        "    Ollama 응답 대기 중... 첫 실행/서버 재시작 직후에는 "
        "모델 로딩으로 60~90초 동안 출력이 없을 수 있습니다.\n"
    )
    sys.stdout.flush()

    response_iter = client.chat(
        model=model,
        messages=messages,
        options=options,
        format=format,
        keep_alive=keep_alive,
        stream=True,
    )

    parts: list[str] = []
    chunk_count = 0
    last_report = 0.0
    start = _time.time()
    try:
        for chunk in response_iter:
            piece = chunk.get("message", {}).get("content", "") if isinstance(chunk, dict) \
                    else getattr(chunk, "message", None) and chunk.message.content or ""
            if piece:
                parts.append(piece)
                chunk_count += 1
                now = _time.time()
                if now - last_report >= 3.0:
                    elapsed = int(now - start)
                    sys.stdout.write(f"\r    생성 중... {chunk_count}청크 ({elapsed}s 경과)")
                    sys.stdout.flush()
                    last_report = now
    except Exception as e:
        # 부분 결과를 보존하여 상위에 전달
        elapsed = int(_time.time() - start)
        sys.stdout.write(f"\r    스트림 중단 ({chunk_count}청크, {elapsed}s): {type(e).__name__}{' '*20}\n")
        if chunk_count == 0:
            sys.stdout.write(
                "    첫 응답 전에 중단됨. 이전 stuck 이후 Ollama 서버 스케줄러가 "
                "좀비 상태일 수 있습니다.\n"
            )
        sys.stdout.flush()
        e._partial_content = "".join(parts)  # type: ignore[attr-defined]
        e._partial_chunks = chunk_count  # type: ignore[attr-defined]
        raise

    sys.stdout.write(f"\r    생성 완료 ({chunk_count}청크, {int(_time.time()-start)}s 소요){' '*20}\n")
    sys.stdout.flush()
    return "".join(parts), chunk_count, int(_time.time() - start)


def _chat_json_with_retries(
    client,
    *,
    model: str,
    messages: list[dict],
    options: dict,
    keep_alive: str,
    max_retries: int,
    parser,
    label: str,
) -> dict:
    import sys
    import time as _time

    content = ""
    last_error: Exception | None = None
    last_partial = ""
    for attempt in range(1, max_retries + 1):
        try:
            content, _chunks, _elapsed = _stream_chat(
                client,
                model=model,
                messages=messages,
                options=options,
                format="json",
                keep_alive=keep_alive,
            )
            try:
                return parser(content)
            except SummaryParseError as e:
                last_error = e
                if attempt < max_retries:
                    backoff = 3 * attempt
                    sys.stdout.write(
                        f"    {label} JSON 검증 실패 — 재시도 {attempt}/{max_retries - 1} "
                        f"({backoff}s 후, 응답 앞부분: {content.strip()[:80]!r})...\n"
                    )
                    sys.stdout.flush()
                    _time.sleep(backoff)
                    continue
                raise
        except SummaryParseError:
            raise
        except Exception as e:
            last_error = e
            partial = getattr(e, "_partial_content", "") or ""
            if len(partial) > len(last_partial):
                last_partial = partial
            if attempt < max_retries:
                backoff = 3 * attempt
                sys.stdout.write(
                    f"    {label} 재시도 {attempt}/{max_retries - 1} "
                    f"({type(e).__name__}, {backoff}s 후)...\n"
                )
                sys.stdout.flush()
                _time.sleep(backoff)
            else:
                sys.stdout.write(
                    f"    {label} 모든 재시도 실패 — partial {len(last_partial)}자로 복구 시도\n"
                )
                sys.stdout.flush()
                content = last_partial

    if last_error is not None and not content.strip() and not last_partial:
        raise RuntimeError(
            "Ollama가 첫 응답을 보내지 못했습니다. 이전 stuck 이후 서버 스케줄러가 "
            f"좀비 상태일 수 있습니다. 'ollama stop {model}' 또는 Ollama 재시작 후 "
            "다시 실행하세요. STT 캐시가 있으면 다음 실행은 요약 단계부터 이어집니다."
        ) from last_error

    try:
        return parser(content)
    except SummaryParseError as e:
        raise RuntimeError(
            f"{label} 응답을 JSON으로 복구하지 못했습니다. "
            f"응답 앞부분: {content.strip()[:200]!r}. "
            "STT 캐시가 있으면 다음 실행은 요약 단계부터 이어집니다."
        ) from e


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
    return {
        "index": chunk_index,
        "time_range": time_range,
        "title": parsed["title"],
        "summary_md": parsed["summary_md"],
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
    model: str,
    max_ctx: int,
    num_predict: int,
    num_gpu: int | None,
    keep_alive: str,
    max_retries: int,
) -> str:
    user_msg = (
        f"아래 구간별 상세 요약을 바탕으로 최종 회의록의 `{heading}` 섹션만 작성하세요.\n"
        f"{instructions}\n"
        "반드시 JSON 객체 하나만 출력하세요. 스키마는 {\"summary_md\": \"...\"} 입니다. "
        f"summary_md는 반드시 `{heading}` 헤더로 시작해야 합니다.\n\n"
        f"--- 구간별 상세 요약 시작 ---\n{material}\n--- 구간별 상세 요약 끝 ---"
    )
    options = _build_ollama_options(
        material,
        max_ctx=max_ctx,
        num_predict=max(2048, min(num_predict, 4096)),
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
    sys.stdout.write("    최종 통합 요약이 필수 섹션을 놓쳐서 섹션별 보강 요약으로 전환합니다.\n")
    sys.stdout.flush()

    sections = []
    for heading, instructions, min_chars in FINAL_SECTION_SPECS:
        sections.append(
            _summarize_final_section(
                client,
                material,
                heading=heading,
                instructions=instructions,
                min_summary_chars=min_chars,
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
        "결정 사항·액션 아이템을 풍부하게 보존하세요. "
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

    user_msg = (
        "다음 회의 대화를 **풍성하고 구체적으로** 정리해 주십시오. "
        "각 섹션은 짧게 끝내지 말고 충실히 채우고, 회의에서 언급된 모든 안건/사례/정책/인물/숫자를 빠짐없이 포함하세요. "
        "**반드시 {\"title\": \"...\", \"summary_md\": \"...\"} 형태의 JSON만 출력**. "
        "JSON 외 다른 텍스트 일절 금지. 응답 첫 글자는 반드시 `{`여야 하며, "
        "`##` 같은 마크다운 헤더로 시작하면 안 됩니다.\n\n"
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


if __name__ == "__main__":
    sample = [
        {"speaker": "사용자1", "text": "다음 주 출시 일정 확정해야 할 것 같습니다."},
        {"speaker": "사용자2", "text": "QA가 수요일까지 끝나니까 금요일 출시 어때요?"},
        {"speaker": "사용자1", "text": "좋습니다. 금요일 오전 10시로 합시다."},
        {"speaker": "사용자3", "text": "릴리즈 노트는 제가 목요일까지 정리하겠습니다."},
    ]
    out = summarize(sample)
    print(json.dumps(out, ensure_ascii=False, indent=2))
