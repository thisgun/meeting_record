from src.g5_client import _compact_remote_text, _non_json_message, _remote_error_message


def test_remote_error_uses_short_server_error() -> None:
    message = _remote_error_message(
        "https://example.test/plugin/meeting_api/post.php",
        500,
        data={"ok": False, "error": "Server misconfigured"},
        text="<html>debug page with stack trace</html>",
    )

    assert "HTTP 500: Server misconfigured" in message
    assert "stack trace" not in message


def test_non_json_response_hides_body_by_default(monkeypatch) -> None:
    monkeypatch.delenv("G5_DEBUG_HTTP", raising=False)

    message = _non_json_message("https://example.test/health.php", 502, "<html>secret debug</html>")

    assert "HTTP 502" in message
    assert "secret debug" not in message


def test_compact_remote_text_normalizes_whitespace_and_truncates() -> None:
    value = _compact_remote_text("a\n\n" + ("b" * 300), limit=20)

    assert "\n" not in value
    assert len(value) == 20
    assert value.endswith("...")
