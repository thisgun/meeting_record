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
