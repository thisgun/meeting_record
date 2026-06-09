"""src/whisper_prompt.py — 파일명 힌트 추출/프롬프트 결합 테스트."""
from pathlib import Path

from src.whisper_prompt import _combine_whisper_prompt, _source_terms_from_filename


def test_source_terms_extracts_and_filters():
    terms = _source_terms_from_filename(Path("[스튜디오 장삐쭈] 산업안전 강화 회의 2026.mp3"))
    assert "장삐쭈" in terms and "산업안전" in terms
    assert "회의" not in terms      # 불용어
    assert "2026" not in terms      # 4자리 이상 숫자 제외


def test_source_terms_dedup_and_max():
    terms = _source_terms_from_filename(Path("가가 가가 나나 다다 라라 마마.mp3"), max_terms=3)
    assert terms.count("가가") == 1          # 중복 제거
    assert len(terms) <= 3                    # max_terms 제한


def test_combine_prompt_includes_hint_and_base():
    p = _combine_whisper_prompt("기본프롬프트", ["산업안전", "장삐쭈"])
    assert "파일명 힌트: 산업안전, 장삐쭈." in p
    assert "기본프롬프트" in p


def test_combine_prompt_truncates_to_300():
    assert len(_combine_whisper_prompt("x" * 500, ["a"])) <= 300


def test_combine_prompt_empty():
    assert _combine_whisper_prompt("", []) == ""
