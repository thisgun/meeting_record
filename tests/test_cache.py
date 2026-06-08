"""STT 캐시 키가 모델/언어에 따라 분리되는지 검증 (모델 바꾸면 자동 재전사)."""
from src import cache


def test_cache_key_varies_by_model(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 100)

    p_small = cache.segments_cache_path(audio, tmp_path, model="small", language="ko")
    p_large = cache.segments_cache_path(audio, tmp_path, model="large-v3", language="ko")
    assert p_small != p_large, "모델이 다르면 캐시 경로도 달라야 한다"


def test_cache_key_stable_for_same_args(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 100)
    a = cache.segments_cache_path(audio, tmp_path, model="small", language="ko")
    b = cache.segments_cache_path(audio, tmp_path, model="small", language="ko")
    assert a == b


def test_cache_key_varies_by_language(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 100)
    ko = cache.segments_cache_path(audio, tmp_path, model="small", language="ko")
    en = cache.segments_cache_path(audio, tmp_path, model="small", language="en")
    assert ko != en


def test_cache_path_is_in_workdir_with_json_suffix(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 10)
    p = cache.segments_cache_path(audio, tmp_path, model="small")
    assert p.parent == tmp_path
    assert p.name.startswith("meeting.")
    assert p.name.endswith(".segments.json")
