"""게시글/요약 본문 하단에 붙일 처리 정보 푸터.

오디오 길이·처리 시간·화자 수·발화 수·STT 모델을 한 줄 마크다운으로 만든다.
순수 함수만 두어 단위 테스트가 쉽도록 한다 (무거운 의존성 import 없음).
"""
from __future__ import annotations


def format_hms(seconds: float) -> str:
    """초를 '1시간 2분 3초' / '2분 3초' / '3초' 형태의 한국어로 변환."""
    total = int(round(seconds)) if seconds and seconds > 0 else 0
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}시간 {minutes}분 {secs}초"
    if minutes:
        return f"{minutes}분 {secs}초"
    return f"{secs}초"


def format_processing_footer(
    *,
    duration_sec: float,
    elapsed_sec: float,
    whisper_model: str,
    speaker_count: int,
    utterance_count: int,
) -> str:
    """summary_md 끝에 덧붙일 처리 정보 마크다운 푸터(앞에 구분선 포함)."""
    return (
        "\n\n---\n"
        f"*🎙 오디오 {format_hms(duration_sec)} · "
        f"⏱ 처리 {format_hms(elapsed_sec)} · "
        f"🗣 화자 {speaker_count}명 · "
        f"💬 발화 {utterance_count}건 · "
        f"🤖 Whisper {whisper_model}*"
    )
