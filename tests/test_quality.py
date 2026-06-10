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


def test_solo_lecture_not_blocked_by_speaker_warning() -> None:
    """1인 강의/보고처럼 화자가 1명인 정상 녹음은 'single_speaker_long' 경고가
    떠도, 내용 품질 경고가 1개뿐이면 danger로 승격되어 차단되면 안 된다.
    (화자 분포 경고는 danger 승격 산정에서 제외 — Codex 지적 ③ 반영)"""
    # 서로 다른 16개 문장(반복 경고 회피) + 약간 낮은 신뢰도 → 강한 경고는 low_asr_confidence 1개.
    sentences = [
        "올해 예산은 작년보다 다소 늘어난 규모로 편성되었습니다",
        "신규 직원 다섯 명이 이번 달부터 현장에 배치됩니다",
        "지난주 안전 점검에서 몇 가지 위험 요소가 확인되었습니다",
        "고객 문의 응대 시간이 평균 십 분 이상 단축되었어요",
        "창고 재고는 분기 말 기준으로 적정 수준을 유지 중입니다",
        "협력업체 세 곳에 대한 정기 평가가 어제 마무리됐습니다",
        "다음 달 직무 교육은 온라인과 오프라인을 병행합니다",
        "전산 시스템 노후 서버를 단계적으로 교체할 예정입니다",
        "민원 처리 절차를 간소화해 대기 시간을 줄였습니다",
        "현장 작업자 보호 장비 지급률이 크게 향상되었습니다",
        "제품 불량률이 전월 대비 절반 가까이 떨어졌습니다",
        "물류 배송 경로를 재설계해 연료비를 크게 아꼈습니다",
        "이번 분기 마케팅 캠페인 반응이 기대 이상으로 좋았습니다",
        "연구팀이 새로운 시제품 개발에 곧 착수한다고 합니다",
        "법무 검토 결과 계약서 일부 조항을 수정하기로 했습니다",
        "회계 결산은 다음 주 금요일까지 완료될 전망입니다",
    ]
    segments = [
        {
            "speaker": "사용자1",
            "start": i * 8.0,
            "end": i * 8.0 + 8.0,
            "text": text,
            "avg_logprob": -1.0,   # 평균 -1.0 → low_asr_confidence '경고'(danger 아님)
        }
        for i, text in enumerate(sentences)
    ]

    report = quality.analyze_segments(segments, duration_sec=300)
    codes = {issue.code for issue in report.issues}

    assert "single_speaker_long" in codes
    assert "low_asr_confidence" in codes
    assert "low_text_amount" not in codes          # 텍스트는 충분
    assert "repeated_text" not in codes            # 문장이 서로 다름
    assert report.severity != "danger", "정상 1인 녹음이 화자 경고만으로 차단되면 안 된다"
    assert not report.should_block_upload


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
