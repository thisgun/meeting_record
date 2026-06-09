"""src/post_footer.py — 처리 정보 푸터 포맷 테스트."""
from src import post_footer


def test_format_hms_seconds_only():
    assert post_footer.format_hms(45) == "45초"


def test_format_hms_minutes():
    assert post_footer.format_hms(125) == "2분 5초"


def test_format_hms_hours():
    assert post_footer.format_hms(3661) == "1시간 1분 1초"


def test_format_hms_rounds_and_clamps_negative():
    assert post_footer.format_hms(0) == "0초"
    assert post_footer.format_hms(-5) == "0초"      # 음수는 0으로 클램프
    assert post_footer.format_hms(59.6) == "1분 0초"  # 반올림 → 60초 → 1분 0초


def test_format_processing_footer_contains_all_fields():
    footer = post_footer.format_processing_footer(
        duration_sec=1710,        # 28분 30초
        elapsed_sec=252,          # 4분 12초
        whisper_model="large-v3",
        speaker_count=5,
        utterance_count=312,
    )
    # 구분선으로 본문과 분리
    assert footer.startswith("\n\n---\n")
    assert "오디오 28분 30초" in footer
    assert "처리 4분 12초" in footer
    assert "화자 5명" in footer
    assert "발화 312건" in footer
    assert "Whisper large-v3" in footer


def test_footer_appends_cleanly_to_markdown():
    body = "# 제목\n\n요약 내용"
    footer = post_footer.format_processing_footer(
        duration_sec=60, elapsed_sec=30, whisper_model="small",
        speaker_count=2, utterance_count=10,
    )
    combined = body + footer
    # 기존 본문은 그대로 보존
    assert combined.startswith("# 제목\n\n요약 내용")
    assert combined.count("---") == 1
