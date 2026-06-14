"""게시판 모더레이션 LLM 로직 (Ollama).

- classify_content: 글/댓글을 spam/ad/abuse/normal로 분류 (+신뢰도/사유)
- summarize_and_tag: 정상 긴 글의 3줄 요약 + 검색용 태그 생성

워처(moderator.py)가 cfg의 Ollama 설정을 넘겨 호출한다.
"""
from __future__ import annotations

import json
import re


CATEGORIES = ("spam", "ad", "abuse", "normal")
CATEGORY_LABEL_KO = {
    "spam": "스팸/도배",
    "ad": "광고/홍보",
    "abuse": "욕설/비방",
    "normal": "정상",
}

CLASSIFY_SYSTEM = """당신은 한국어 커뮤니티 게시판 모더레이터입니다. 주어진 글을 다음 한 가지로 분류하십시오.

- spam: 의미 없는 도배, 반복, 외부 링크 도배, 피싱/악성 유도
- ad: 상업적 광고, 판매·홍보, 영업 문의 유도
- abuse: 욕설, 비방, 혐오, 인신공격, 차별 표현
- normal: 위에 해당하지 않는 정상적인 글

**오직 하나의 JSON 객체만 출력하십시오. 코드펜스나 다른 텍스트 금지.**
스키마: {"category": "spam|ad|abuse|normal", "confidence": 0.0~1.0, "reason": "한 문장 한국어 근거"}
정상으로 의심되면 normal로, 확실할 때만 높은 confidence를 부여하십시오."""

SUMMARY_SYSTEM = """당신은 게시판 글을 요약하고 태그를 다는 도우미입니다.
주어진 글을 한국어로 3줄 이내로 요약하고, 검색에 도움이 될 핵심 태그 3~6개를 뽑으십시오.

**오직 하나의 JSON 객체만 출력하십시오. 코드펜스나 다른 텍스트 금지.**
스키마: {"summary": "3줄 이내 요약(줄바꿈 \\n 허용)", "tags": ["태그1", "태그2", ...]}
태그는 한두 단어의 명사구로, 본문에 등장하거나 본문을 대표하는 개념으로 만드십시오."""


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _ollama_json(
    system: str,
    user: str,
    *,
    model: str,
    host: str,
    timeout: float = 120.0,
    keep_alive: str = "0",
    num_ctx: int = 8192,
    num_predict: int = 512,
    num_gpu: int | None = None,
) -> dict:
    try:
        from ollama import Client
    except ImportError as e:
        raise RuntimeError("ollama 패키지가 필요합니다: pip install ollama") from e

    client = Client(host=host, timeout=timeout)
    options = {"temperature": 0.0, "num_ctx": num_ctx, "num_predict": num_predict}
    if num_gpu is not None:
        options["num_gpu"] = num_gpu
    resp = client.chat(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        options=options,
        format="json",
        keep_alive=keep_alive,
    )
    content = resp.get("message", {}).get("content", "") if isinstance(resp, dict) \
        else resp.message.content
    return _parse_json(content)


def _trim(text: str, limit: int = 4000) -> str:
    text = (text or "").strip()
    return text[:limit]


def classify_content(
    text: str,
    *,
    model: str,
    host: str,
    timeout: float = 120.0,
    keep_alive: str = "0",
    num_ctx_max: int = 8192,
    num_gpu: int | None = None,
) -> dict:
    """글/댓글 분류. {category, confidence, reason} 반환 (실패 시 normal/0)."""
    body = _trim(text)
    if not body:
        return {"category": "normal", "confidence": 0.0, "reason": "빈 내용"}
    num_ctx = min(num_ctx_max, max(2048, (len(body) // 1024 + 2) * 1024))
    data = _ollama_json(
        CLASSIFY_SYSTEM, f"다음 글을 분류하십시오:\n\n{body}",
        model=model, host=host, timeout=timeout, keep_alive=keep_alive,
        num_ctx=num_ctx, num_predict=200, num_gpu=num_gpu,
    )
    cat = str(data.get("category", "normal")).lower().strip()
    if cat not in CATEGORIES:
        cat = "normal"
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    reason = str(data.get("reason", "")).strip()[:300]
    return {"category": cat, "confidence": conf, "reason": reason}


def summarize_and_tag(
    text: str,
    *,
    model: str,
    host: str,
    timeout: float = 120.0,
    keep_alive: str = "0",
    num_ctx_max: int = 8192,
    num_gpu: int | None = None,
) -> dict:
    """정상 긴 글 요약 + 태그. {summary, tags} 반환 (실패 시 빈 값)."""
    body = _trim(text)
    if not body:
        return {"summary": "", "tags": []}
    num_ctx = min(num_ctx_max, max(2048, (len(body) // 1024 + 2) * 1024))
    data = _ollama_json(
        SUMMARY_SYSTEM, f"다음 글을 요약하고 태그를 뽑으십시오:\n\n{body}",
        model=model, host=host, timeout=timeout, keep_alive=keep_alive,
        num_ctx=num_ctx, num_predict=512, num_gpu=num_gpu,
    )
    summary = str(data.get("summary", "")).strip()
    tags_raw = data.get("tags", [])
    tags: list[str] = []
    if isinstance(tags_raw, list):
        for t in tags_raw:
            t = str(t).strip().lstrip("#").strip()
            if t and t not in tags:
                tags.append(t)
    return {"summary": summary, "tags": tags[:8]}
