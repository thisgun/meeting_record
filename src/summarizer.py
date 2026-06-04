"""Ollama gemma4:e2b 기반 회의 요약."""
from __future__ import annotations

import json
import re


SYSTEM_PROMPT = """당신은 한국어 회의록 정리 전문가입니다. 회의 transcript에서 빠진 디테일 없이 풍부하고 구체적인 회의록을 작성합니다.

**출력 규칙 (절대 위반 금지):**
1. 응답은 **오직 하나의 JSON 객체**여야 합니다.
2. JSON 앞뒤에 어떠한 설명, 코드펜스(```), 추가 텍스트도 넣지 마십시오.
3. JSON 객체는 정확히 두 개의 키 `title`과 `summary_md`만 가집니다.

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


def _format_transcript(utterances: list[dict]) -> str:
    lines = []
    for u in utterances:
        speaker = u.get("speaker", "?")
        text = (u.get("text") or "").strip()
        if text:
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


def summarize(
    utterances: list[dict],
    *,
    model: str = "gemma4:e2b",
    host: str = "http://127.0.0.1:11434",
    timeout: float = 1800.0,
    keep_alive: str = "60m",
) -> dict:
    """발화 리스트를 받아 {title, summary_md} 반환."""
    try:
        from ollama import Client
    except ImportError as e:
        raise RuntimeError("ollama 패키지가 필요합니다: pip install ollama") from e

    if not utterances:
        return {"title": "(빈 회의)", "summary_md": "_발화 내용이 없습니다._"}

    transcript = _format_transcript(utterances)
    client = Client(host=host, timeout=timeout)

    # 긴 회의 대비: context window를 토큰 추정치에 따라 동적 설정
    # 한국어는 평균 ~2.5자/토큰 → transcript 문자수 × 0.4 토큰 추정 + 여유
    approx_tokens = int(len(transcript) * 0.5) + 2048
    num_ctx = min(131072, max(4096, ((approx_tokens // 1024) + 1) * 1024))

    user_msg = (
        "다음 회의 대화를 **풍성하고 구체적으로** 정리해 주십시오. "
        "각 섹션은 짧게 끝내지 말고 충실히 채우고, 회의에서 언급된 모든 안건/사례/정책/인물/숫자를 빠짐없이 포함하세요. "
        "**반드시 {\"title\": \"...\", \"summary_md\": \"...\"} 형태의 JSON만 출력**. "
        "JSON 외 다른 텍스트 일절 금지.\n\n"
        f"--- 회의 대화 시작 ---\n{transcript}\n--- 회의 대화 끝 ---"
    )

    # 스트리밍 응답 — 토큰 사이 idle만 timeout 적용되므로 전체 처리가 길어도 안 끊김
    # 동시에 진행 상황 표시 (마지막 줄에 "생성 중... N토큰" 갱신)
    import sys
    response_iter = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        options={
            "temperature": 0.2,
            "num_ctx": num_ctx,
            "num_predict": 16384,  # 풍성한 요약을 위해 응답 토큰 한도 확대
        },
        format="json",
        keep_alive=keep_alive,
        stream=True,
    )

    parts: list[str] = []
    token_count = 0
    last_report = 0.0
    import time as _time
    start = _time.time()
    for chunk in response_iter:
        piece = chunk.get("message", {}).get("content", "") if isinstance(chunk, dict) \
                else getattr(chunk, "message", None) and chunk.message.content or ""
        if piece:
            parts.append(piece)
            token_count += 1
            now = _time.time()
            if now - last_report >= 3.0:
                elapsed = int(now - start)
                sys.stdout.write(f"\r    생성 중... {token_count}청크 ({elapsed}s 경과)")
                sys.stdout.flush()
                last_report = now
    sys.stdout.write(f"\r    생성 완료 ({token_count}청크, {int(_time.time()-start)}s 소요){' '*20}\n")
    sys.stdout.flush()
    content = "".join(parts)

    try:
        data = _extract_json(content)
    except (ValueError, json.JSONDecodeError) as e:
        # JSON 파싱 실패 시 fallback
        return {
            "title": "회의록 (자동 생성 실패)",
            "summary_md": f"_요약 파싱 실패: {e}_\n\n원본 응답:\n\n{content}",
        }

    title = str(data.get("title") or "회의록").strip()[:200]
    summary_md = str(data.get("summary_md") or "").strip()
    return {"title": title, "summary_md": summary_md}


if __name__ == "__main__":
    sample = [
        {"speaker": "사용자1", "text": "다음 주 출시 일정 확정해야 할 것 같습니다."},
        {"speaker": "사용자2", "text": "QA가 수요일까지 끝나니까 금요일 출시 어때요?"},
        {"speaker": "사용자1", "text": "좋습니다. 금요일 오전 10시로 합시다."},
        {"speaker": "사용자3", "text": "릴리즈 노트는 제가 목요일까지 정리하겠습니다."},
    ]
    out = summarize(sample)
    print(json.dumps(out, ensure_ascii=False, indent=2))
