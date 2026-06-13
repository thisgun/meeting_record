"""app_auth.py — 환경변수 정수 파싱 + 로그인 시도 제한(lockout) 로직 테스트.

(streamlit 불필요 — 순수 함수만 테스트, require_app_auth는 런타임에 lazy import)
"""
import app_auth


def test_env_int(monkeypatch):
    monkeypatch.setenv("X_INT", "42")
    assert app_auth._env_int("X_INT", 0) == 42
    monkeypatch.setenv("X_INT", "abc")          # 잘못된 값 → default
    assert app_auth._env_int("X_INT", 7) == 7
    monkeypatch.delenv("X_INT", raising=False)   # 없음 → default
    assert app_auth._env_int("X_INT", 5) == 5
    monkeypatch.setenv("X_INT", "1")             # min_value 클램프
    assert app_auth._env_int("X_INT", 0, min_value=3) == 3


def test_record_auth_failure_increments(monkeypatch, tmp_path):
    monkeypatch.setenv("STREAMLIT_AUTH_STATE_PATH", str(tmp_path / "auth.json"))
    f1, lock1 = app_auth._record_auth_failure(100.0, max_attempts=3, lockout_sec=300)
    assert (f1, lock1) == (1, 0)
    f2, _ = app_auth._record_auth_failure(100.0, max_attempts=3, lockout_sec=300)
    assert f2 == 2


def test_record_auth_failure_locks_after_max(monkeypatch, tmp_path):
    monkeypatch.setenv("STREAMLIT_AUTH_STATE_PATH", str(tmp_path / "auth.json"))
    app_auth._record_auth_failure(100.0, 2, 300)        # 1회
    failures, locked_until = app_auth._record_auth_failure(100.0, 2, 300)  # 2회 → 잠금
    assert failures == 0
    assert locked_until == 100.0 + 300


def test_reset_clears_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("STREAMLIT_AUTH_STATE_PATH", str(tmp_path / "auth.json"))
    app_auth._record_auth_failure(100.0, 5, 300)
    app_auth._reset_auth_failures()
    assert app_auth._read_auth_state().get("failures") == 0
