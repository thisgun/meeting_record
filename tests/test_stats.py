"""src/stats.py 순수 함수 테스트 (화자/시간 통계·포맷)."""
from src import stats


def test_per_speaker_stats_empty():
    assert stats.per_speaker_stats([]) == []


def test_per_speaker_stats_counts_ratio_sorted():
    utts = [
        {"speaker": "A", "start": 0, "end": 10},
        {"speaker": "B", "start": 10, "end": 40},   # 30s
        {"speaker": "A", "start": 40, "end": 50},   # A 합계 20s
    ]
    out = stats.per_speaker_stats(utts)
    # 발언 시간 내림차순 → B(30) 먼저
    assert [s["speaker"] for s in out] == ["B", "A"]
    a = next(s for s in out if s["speaker"] == "A")
    assert a["count"] == 2 and a["total_sec"] == 20.0 and a["avg_sec"] == 10.0
    assert round(sum(s["ratio_pct"] for s in out)) == 100


def test_per_speaker_handles_alt_keys_and_negative_duration():
    # start_sec/end_sec 키 + 음수 길이 → 0 처리
    out = stats.per_speaker_stats([{"speaker": "A", "start_sec": 5, "end_sec": 0}])
    assert out[0]["total_sec"] == 0.0


def test_time_distribution_bins_and_top_speaker():
    utts = [
        {"speaker": "A", "start": 0, "end": 60},
        {"speaker": "A", "start": 120, "end": 180},
        {"speaker": "B", "start": 700, "end": 760},   # 두 번째 600초 구간
    ]
    out = stats.time_distribution(utts, chunk_sec=600)
    assert len(out) == 2
    assert out[0]["chunk_start"] == 0 and out[0]["count"] == 2 and out[0]["top_speaker"] == "A"
    assert out[1]["chunk_start"] == 600 and out[1]["top_speaker"] == "B"


def test_time_distribution_empty():
    assert stats.time_distribution([]) == []


def test_format_duration():
    assert stats.format_duration(45) == "45초"
    assert stats.format_duration(125) == "2분 5초"
    assert stats.format_duration(3725) == "1시간 2분"


def test_format_speaker_table_contains_data():
    table = stats.format_speaker_table(
        stats.per_speaker_stats([{"speaker": "사용자1", "start": 0, "end": 10}])
    )
    assert "사용자1" in table
    assert "화자" in table
