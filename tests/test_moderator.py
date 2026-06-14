"""게시판 모더레이션 LLM 로직 단위 테스트 (Ollama 호출은 더미로 대체)."""
from src import moderator


def test_parse_json_variants() -> None:
    assert moderator._parse_json('{"a": 1}') == {"a": 1}
    assert moderator._parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert moderator._parse_json('설명입니다 {"category": "spam"} 끝') == {"category": "spam"}
    assert moderator._parse_json("형식 오류") == {}


def test_classify_normalizes_and_clamps(monkeypatch) -> None:
    monkeypatch.setattr(
        moderator, "_ollama_json",
        lambda *a, **k: {"category": "SPAM", "confidence": 1.5, "reason": "광고성"},
    )
    r = moderator.classify_content("텍스트", model="m", host="h")
    assert r["category"] == "spam"      # 대소문자 정규화
    assert r["confidence"] == 1.0       # 0~1로 clamp
    assert r["reason"] == "광고성"


def test_classify_unknown_category_falls_back_to_normal(monkeypatch) -> None:
    monkeypatch.setattr(
        moderator, "_ollama_json",
        lambda *a, **k: {"category": "weird", "confidence": 0.7},
    )
    assert moderator.classify_content("t", model="m", host="h")["category"] == "normal"


def test_classify_empty_text_skips_llm() -> None:
    r = moderator.classify_content("   ", model="m", host="h")
    assert r["category"] == "normal"
    assert r["confidence"] == 0.0


def test_classify_bad_confidence(monkeypatch) -> None:
    monkeypatch.setattr(
        moderator, "_ollama_json",
        lambda *a, **k: {"category": "ad", "confidence": "높음"},
    )
    r = moderator.classify_content("광고", model="m", host="h")
    assert r["category"] == "ad"
    assert r["confidence"] == 0.0  # 숫자 아니면 0


def test_summarize_and_tag_cleans_tags(monkeypatch) -> None:
    monkeypatch.setattr(
        moderator, "_ollama_json",
        lambda *a, **k: {"summary": "세 줄 요약", "tags": ["#신제품", "마케팅", "마케팅", "  배송  "]},
    )
    r = moderator.summarize_and_tag("긴 글 본문", model="m", host="h")
    assert r["summary"] == "세 줄 요약"
    assert r["tags"] == ["신제품", "마케팅", "배송"]  # # 제거, 중복 제거, 공백 trim


def test_summarize_empty_text() -> None:
    r = moderator.summarize_and_tag("", model="m", host="h")
    assert r == {"summary": "", "tags": []}
