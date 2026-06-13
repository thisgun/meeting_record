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


def test_cache_key_varies_by_vad_filter(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 100)
    on = cache.segments_cache_path(audio, tmp_path, model="small", vad_filter=True)
    off = cache.segments_cache_path(audio, tmp_path, model="small", vad_filter=False)
    assert on != off, "VAD 필터를 바꾸면 캐시도 분리돼야 한다"


def test_cache_key_varies_by_condition_on_previous_text(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 100)
    on = cache.segments_cache_path(audio, tmp_path, model="small", condition_on_previous_text=True)
    off = cache.segments_cache_path(audio, tmp_path, model="small", condition_on_previous_text=False)
    assert on != off


def test_cache_key_varies_by_prompt(tmp_path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 100)
    a = cache.segments_cache_path(audio, tmp_path, model="small", prompt="와일드씽 트라이앵글")
    b = cache.segments_cache_path(audio, tmp_path, model="small", prompt="산업안전 노동부")
    none = cache.segments_cache_path(audio, tmp_path, model="small")
    assert a != b, "initial_prompt가 다르면 캐시도 분리돼야 한다"
    assert a != none


def test_cache_key_backward_compatible(tmp_path):
    """새 인자를 안 주면 과거(모델/언어만)와 동일한 키 — 하위호환."""
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"x" * 100)
    legacy = cache.segments_cache_path(audio, tmp_path, model="small", language="ko")
    same = cache.segments_cache_path(
        audio, tmp_path, model="small", language="ko",
        vad_filter=None, condition_on_previous_text=None, prompt="",
    )
    assert legacy == same
