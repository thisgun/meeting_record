"""src/comparator.py 키워드 추출(정규식 경로) 테스트 — kiwipiepy 불필요."""
from src import comparator


def test_korean_words_extracts_2_to_12_char_runs():
    assert comparator._korean_words("산업안전 강화abc123!!") == ["산업안전", "강화"]
    assert comparator._korean_words("가 한글") == ["한글"]  # 1글자 제외


def test_top_keywords_counts_filters_stopwords_and_min_count():
    texts = [
        "산업안전 강화 산업안전 점검",
        "산업안전 사고 예방 사고 예방",
        "회의 내용",  # 둘 다 불용어
    ]
    d = dict(comparator.top_keywords(texts, method="regex", min_count=2, top_n=10))
    assert d.get("산업안전") == 3
    assert d.get("사고") == 2
    assert d.get("예방") == 2
    assert "강화" not in d and "점검" not in d   # min_count=2 미만
    assert "회의" not in d and "내용" not in d    # 불용어 제외


def test_top_keywords_exclude_and_top_n():
    texts = ["보고서 보고서 보고서 일정 일정"]
    d = dict(comparator.top_keywords(
        texts, method="regex", min_count=2, top_n=1, exclude={"보고서"}))
    assert list(d.keys()) == ["일정"]   # 보고서 제외 + top_n=1
