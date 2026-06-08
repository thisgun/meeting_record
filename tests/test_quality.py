from src import quality


def test_quality_report_blocks_empty_long_audio() -> None:
    report = quality.analyze_segments([], duration_sec=300)

    assert report.severity == "danger"
    assert report.should_block_upload
    assert any(issue.code == "no_speech" for issue in report.issues)


def test_quality_warns_when_long_recording_has_one_speaker() -> None:
    segments = [
        {
            "speaker": "사용자1",
            "start": i * 12.0,
            "end": i * 12.0 + 5.0,
            "text": f"회의 발화 {i}입니다. 다음 안건을 이야기합니다.",
        }
        for i in range(20)
    ]

    report = quality.analyze_segments(segments, duration_sec=360)

    assert any(issue.code == "single_speaker_long" for issue in report.issues)


def test_quality_blocks_repeated_low_confidence_transcript() -> None:
    segments = [
        {
            "speaker": "사용자1",
            "start": i * 10.0,
            "end": i * 10.0 + 4.0,
            "text": "같은 문장이 계속 반복됩니다.",
            "avg_logprob": -1.4,
        }
        for i in range(12)
    ]

    report = quality.analyze_segments(segments, duration_sec=240)

    assert report.severity == "danger"
    assert report.should_block_upload
    assert any(issue.code == "repeated_text" for issue in report.issues)
    assert any(issue.code == "low_asr_confidence" for issue in report.issues)


def test_quality_notice_is_prepended_to_summary() -> None:
    report = quality.analyze_segments([], duration_sec=180)

    summary = quality.prepend_quality_notice("## 회의 개요\n- 내용", report)

    assert summary.startswith("## 품질 경고")
    assert "## 회의 개요" in summary
