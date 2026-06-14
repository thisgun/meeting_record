"""src/notifier.py — 알림 설정 감지(is_configured) 테스트."""
from src import notifier

_KEYS = [
    "NOTIFY_SLACK_WEBHOOK", "NOTIFY_EMAIL_HOST", "NOTIFY_EMAIL_USER",
    "NOTIFY_EMAIL_TO", "NOTIFY_LEVEL",
]


def _clear(monkeypatch):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)


def test_is_configured_none(monkeypatch):
    _clear(monkeypatch)
    cfg = notifier.is_configured()
    assert cfg["slack"] is False
    assert cfg["email"] is False
    assert isinstance(cfg["level"], str)


def test_is_configured_slack(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NOTIFY_SLACK_WEBHOOK", "https://hooks.slack.com/x")
    assert notifier.is_configured()["slack"] is True


def test_is_configured_email_requires_all(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NOTIFY_EMAIL_HOST", "smtp.example.com")
    assert notifier.is_configured()["email"] is False   # USER/TO 없음
    monkeypatch.setenv("NOTIFY_EMAIL_USER", "u@example.com")
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "t@example.com")
    assert notifier.is_configured()["email"] is True


def test_notify_alert_off_level_skips(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NOTIFY_LEVEL", "off")
    sent = []
    monkeypatch.setattr(notifier, "_send_slack", lambda *a, **k: sent.append("slack") or True)
    monkeypatch.setattr(notifier, "_send_email", lambda *a, **k: sent.append("email") or True)
    assert notifier.notify_alert("제목", "본문") is False
    assert sent == []  # off면 채널 호출 안 함


def test_notify_alert_fail_level_sends_failures_only(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NOTIFY_LEVEL", "fail")
    monkeypatch.setattr(notifier, "_send_slack", lambda *a, **k: True)
    monkeypatch.setattr(notifier, "_send_email", lambda *a, **k: False)
    assert notifier.notify_alert("오류", "본문", success=False) is True   # 실패 알림 전송
    assert notifier.notify_alert("복구", "본문", success=True) is False   # 성공 알림은 스킵


def test_notify_alert_no_channels(monkeypatch):
    _clear(monkeypatch)  # 채널 미설정 → 전송 실패(False)
    assert notifier.notify_alert("제목", "본문", success=False) is False
