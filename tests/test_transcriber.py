from src import transcriber


def test_should_retry_without_vad_for_sparse_long_audio() -> None:
    segments = [
        {"start": 20.0, "end": 30.0, "text": "첫 번째 발화입니다."},
        {"start": 200.0, "end": 210.0, "text": "두 번째 발화입니다."},
        {"start": 360.0, "end": 370.0, "text": "세 번째 발화입니다."},
    ]

    assert transcriber._should_retry_without_vad(segments, 390.0)


def test_should_not_retry_without_vad_for_dense_meeting_audio() -> None:
    segments = [
        {"start": i * 10.0, "end": i * 10.0 + 4.0, "text": "회의 발화입니다."}
        for i in range(30)
    ]

    assert not transcriber._should_retry_without_vad(segments, 300.0)


def test_prefer_vad_retry_when_retry_has_much_more_text() -> None:
    original = [
        {"start": 10.0, "end": 20.0, "text": "짧은 발화입니다."},
        {"start": 80.0, "end": 90.0, "text": "또 짧은 발화입니다."},
    ]
    retry = original + [
        {"start": 95.0, "end": 110.0, "text": "재시도에서 더 많은 실제 발화가 잡혔습니다."},
        {"start": 120.0, "end": 140.0, "text": "누락된 발화가 추가로 인식되었습니다."},
        {"start": 150.0, "end": 170.0, "text": "회의 내용이 더 촘촘하게 들어왔습니다."},
    ]

    assert transcriber._prefer_vad_retry(original, retry, 300.0)
