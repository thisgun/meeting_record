"""Streamlit 웹 UI 비밀번호 인증 + 파일 기반 로그인 시도 제한(lockout).

app.py에서 `require_app_auth()` 한 번 호출해 게이트로 사용한다.
"""
from __future__ import annotations

import hmac
import json
import os
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _env_int(name: str, default: int, *, min_value: int = 0) -> int:
    try:
        value = int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default
    return max(min_value, value)


def _auth_state_path() -> Path:
    configured = (os.getenv("STREAMLIT_AUTH_STATE_PATH") or "").strip()
    return Path(configured) if configured else PROJECT_ROOT / "data" / "app_auth_state.json"


def _read_auth_state() -> dict:
    path = _auth_state_path()
    try:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_auth_state(state: dict) -> None:
    path = _auth_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        tmp.replace(path)
    except Exception:
        # File-backed lockout is best effort; session_state still protects this browser session.
        return


def _reset_auth_failures() -> None:
    _write_auth_state({"failures": 0, "locked_until": 0})


def _record_auth_failure(now: float, max_attempts: int, lockout_sec: int) -> tuple[int, float]:
    state = _read_auth_state()
    locked_until = float(state.get("locked_until") or 0)
    if locked_until > now:
        return 0, locked_until
    failures = int(state.get("failures") or 0) + 1
    if failures >= max_attempts:
        locked_until = now + lockout_sec
        _write_auth_state({"failures": 0, "locked_until": locked_until})
        return 0, locked_until
    _write_auth_state({"failures": failures, "locked_until": 0})
    return failures, 0


def require_app_auth() -> None:
    import streamlit as st

    allow_no_auth = os.getenv("STREAMLIT_ALLOW_NO_AUTH", "").lower().strip() in ("1", "true", "yes", "on")
    if allow_no_auth:
        st.warning("STREAMLIT_ALLOW_NO_AUTH가 켜져 있어 웹 UI 인증을 건너뜁니다.")
        return

    password = os.getenv("STREAMLIT_ACCESS_PASSWORD", "").strip()
    if not password:
        st.error("STREAMLIT_ACCESS_PASSWORD가 설정되지 않아 웹 UI를 잠갔습니다.")
        st.code("STREAMLIT_ACCESS_PASSWORD=강력한-비밀번호", language="dotenv")
        st.stop()

    now = time.time()
    session_ttl_sec = _env_int("STREAMLIT_SESSION_TTL_SEC", 12 * 60 * 60)
    if st.session_state.get("app_authenticated"):
        authenticated_at = float(st.session_state.get("app_authenticated_at") or now)
        if session_ttl_sec > 0 and now - authenticated_at > session_ttl_sec:
            st.session_state.pop("app_authenticated", None)
            st.session_state.pop("app_authenticated_at", None)
            st.warning("로그인 세션이 만료되었습니다. 다시 로그인하세요.")
        else:
            return

    auth_state = _read_auth_state()
    locked_until = max(
        float(st.session_state.get("app_auth_locked_until") or 0),
        float(auth_state.get("locked_until") or 0),
    )
    if locked_until > now:
        remaining = int(locked_until - now) + 1
        st.title("회의록 관리")
        st.error(f"로그인 시도가 잠시 제한되었습니다. {remaining}초 후 다시 시도하세요.")
        st.stop()

    max_attempts = _env_int("STREAMLIT_AUTH_MAX_ATTEMPTS", 5, min_value=1)
    lockout_sec = _env_int("STREAMLIT_AUTH_LOCKOUT_SEC", 300, min_value=1)

    if st.session_state.get("app_authenticated"):
        return

    st.title("회의록 관리")
    entered = st.text_input("비밀번호", type="password")
    if st.button("로그인"):
        if hmac.compare_digest(entered, password):
            st.session_state["app_authenticated"] = True
            st.session_state["app_authenticated_at"] = now
            st.session_state["app_auth_failures"] = 0
            st.session_state["app_auth_locked_until"] = 0
            _reset_auth_failures()
            st.rerun()
        failures, locked_until = _record_auth_failure(now, max_attempts, lockout_sec)
        st.session_state["app_auth_failures"] = failures
        st.session_state["app_auth_locked_until"] = locked_until
        if locked_until > now:
            st.session_state["app_auth_failures"] = 0
            st.error(f"로그인 시도가 너무 많습니다. {lockout_sec}초 후 다시 시도하세요.")
        else:
            remaining = max_attempts - failures
            st.error(f"비밀번호가 맞지 않습니다. 남은 시도: {remaining}회")
    st.stop()
