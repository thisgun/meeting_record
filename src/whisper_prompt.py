"""파일명에서 STT(Whisper) 힌트 용어 추출 + initial_prompt 결합.

파일명에 담긴 작품명·인명·기관명 등을 Whisper의 initial_prompt 힌트로 넘기면
고유명사 인식 정확도가 올라간다.
"""
from __future__ import annotations

import re
from pathlib import Path


def _source_terms_from_filename(path: Path, *, max_terms: int = 12) -> list[str]:
    """파일명에서 Whisper/STT 힌트로 쓸 작품명·인명 후보를 추출."""
    stem = path.stem
    stem = re.sub(r"\([^)]*[A-Za-z0-9_-]{6,}[^)]*\)", " ", stem)
    tokens = re.split(r"[\s\[\]\(\),/&·|_+\-]+", stem)
    terms: list[str] = []
    stopwords = {
        "직캠",
        "fancam",
        "회의",
        "복사본",
        "영상",
        "무대인사",
        "full",
        "official",
    }
    for token in tokens:
        term = token.strip(" .!?:;\"'")
        if not term:
            continue
        if term.lower() in stopwords:
            continue
        if re.fullmatch(r"\d{4,}", term):
            continue
        if len(term) < 2:
            continue
        if term not in terms:
            terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def _combine_whisper_prompt(base_prompt: str, source_terms: list[str]) -> str:
    parts = []
    if source_terms:
        parts.append("파일명 힌트: " + ", ".join(source_terms) + ".")
    if base_prompt:
        parts.append(base_prompt)
    prompt = " ".join(parts).strip()
    return prompt[:300]
