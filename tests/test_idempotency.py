"""src/idempotency.py — 원격 멱등성 키 생성 테스트."""
import pytest

from src.idempotency import _remote_idempotency_key, _safe_key_part


def test_safe_key_part_lowercases_and_keeps_allowed():
    assert _safe_key_part("ABC-1.2_x") == "abc-1.2_x"   # 영숫자/.-_ 유지(소문자화)
    assert _safe_key_part("가 나!").replace("_", "") == ""  # 비허용 → 전부 _


def test_remote_key_meeting_level():
    assert _remote_idempotency_key("post", "MEETING-UUID-123", "remote") == \
        "meeting_record:post:meeting-uuid-123:remote"


def test_remote_key_comment_level():
    assert _remote_idempotency_key("comment", "m1", "default", utterance_uuid="u9") == \
        "meeting_record:comment:m1:u9:default"


def test_remote_key_blank_target_defaults():
    assert _remote_idempotency_key("post", "m1", "").endswith(":default")


def test_remote_key_requires_meeting_uuid():
    with pytest.raises(ValueError):
        _remote_idempotency_key("post", "", "remote")


def test_remote_key_requires_utterance_uuid_for_comment():
    with pytest.raises(ValueError):
        _remote_idempotency_key("comment", "m1", "t", utterance_uuid="")
