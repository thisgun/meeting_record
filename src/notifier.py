"""처리 결과 알림 — Slack / 이메일 / 콘솔.

설정된 채널만 작동 (Slack webhook 또는 SMTP). 둘 다 없으면 콘솔 출력만.

.env 설정:
    NOTIFY_SLACK_WEBHOOK=https://hooks.slack.com/...
    NOTIFY_EMAIL_HOST=smtp.gmail.com
    NOTIFY_EMAIL_PORT=587
    NOTIFY_EMAIL_USER=sender@gmail.com
    NOTIFY_EMAIL_PASS=앱비밀번호
    NOTIFY_EMAIL_FROM=sender@gmail.com
    NOTIFY_EMAIL_TO=receiver1@example.com,receiver2@example.com
    NOTIFY_LEVEL=all  # all=성공/실패 모두, fail=실패만, off=알림 끔
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Optional


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _level() -> str:
    """all / fail / off"""
    return _env("NOTIFY_LEVEL", "all").lower()


def _should_send(success: bool) -> bool:
    lv = _level()
    if lv == "off":
        return False
    if lv == "fail":
        return not success
    return True


def _send_slack(text: str, *, color: str = "good") -> bool:
    """Slack incoming webhook으로 전송. attachment 컬러 지원."""
    url = _env("NOTIFY_SLACK_WEBHOOK")
    if not url:
        return False
    payload = {
        "attachments": [{
            "color": color,  # good=초록, warning=노랑, danger=빨강
            "text": text,
            "mrkdwn_in": ["text"],
        }]
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"[notifier] Slack 전송 실패: {e}")
        return False


def _send_email(subject: str, body: str) -> bool:
    """SMTP TLS로 전송."""
    host = _env("NOTIFY_EMAIL_HOST")
    user = _env("NOTIFY_EMAIL_USER")
    password = _env("NOTIFY_EMAIL_PASS")
    sender = _env("NOTIFY_EMAIL_FROM") or user
    to = _env("NOTIFY_EMAIL_TO")
    if not (host and user and password and to):
        return False

    port = int(_env("NOTIFY_EMAIL_PORT", "587"))
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"[notifier] 이메일 전송 실패: {e}")
        return False


def _format_duration(sec: float) -> str:
    if sec < 60:
        return f"{sec:.0f}초"
    if sec < 3600:
        m, s = divmod(int(sec), 60)
        return f"{m}분 {s}초"
    h, rem = divmod(int(sec), 3600)
    m = rem // 60
    return f"{h}시간 {m}분"


def notify_meeting_done(
    *,
    meeting_id: int,
    title: str,
    source_file: str,
    duration_sec: float,
    speaker_count: int,
    utterance_count: int,
    wr_id: Optional[int] = None,
    g5_url: Optional[str] = None,
    elapsed_sec: float = 0,
) -> bool:
    """회의 처리 성공 알림."""
    if not _should_send(success=True):
        return False
    src_name = Path(source_file).name
    text_lines = [
        f"✅ *회의록 처리 완료*",
        f"*제목*: {title}",
        f"*원본*: {src_name}",
        f"*길이*: {_format_duration(duration_sec)} / 발화 {utterance_count}건 / 화자 {speaker_count}명",
        f"*처리 시간*: {_format_duration(elapsed_sec)}",
    ]
    if wr_id and g5_url:
        text_lines.append(f"*게시글*: <{g5_url}|wr_id={wr_id}>")
    elif wr_id:
        text_lines.append(f"*게시글*: wr_id={wr_id}")
    text = "\n".join(text_lines)

    slack_ok = _send_slack(text, color="good")

    email_body = text.replace("*", "")
    email_subject = f"[회의록] 처리 완료: {title}"
    email_ok = _send_email(email_subject, email_body)

    if slack_ok or email_ok:
        channels = []
        if slack_ok: channels.append("Slack")
        if email_ok: channels.append("이메일")
        print(f"    [알림] {', '.join(channels)} 전송 완료")
    return slack_ok or email_ok


def notify_meeting_failed(
    *,
    source_file: str,
    error: str,
    stage: str = "?",
    elapsed_sec: float = 0,
) -> bool:
    """회의 처리 실패 알림."""
    if not _should_send(success=False):
        return False
    src_name = Path(source_file).name
    text = "\n".join([
        f"❌ *회의록 처리 실패*",
        f"*원본*: {src_name}",
        f"*단계*: {stage}",
        f"*경과*: {_format_duration(elapsed_sec)}",
        f"*에러*: ```{error[:500]}```",
    ])
    slack_ok = _send_slack(text, color="danger")
    email_body = text.replace("*", "").replace("```", "")
    email_subject = f"[회의록] 처리 실패: {src_name}"
    email_ok = _send_email(email_subject, email_body)

    if slack_ok or email_ok:
        channels = []
        if slack_ok: channels.append("Slack")
        if email_ok: channels.append("이메일")
        print(f"    [알림] 실패 통보 ({', '.join(channels)})")
    return slack_ok or email_ok


def notify_alert(
    title: str,
    body: str = "",
    *,
    success: bool = False,
    color: Optional[str] = None,
) -> bool:
    """범용 운영 알림 (워처 폴링 오류/복구 등). NOTIFY_LEVEL 정책을 따른다."""
    if not _should_send(success=success):
        return False
    icon = "✅" if success else "⚠️"
    text = f"{icon} *{title}*"
    if body:
        text += f"\n{body[:800]}"
    slack_ok = _send_slack(text, color=color or ("good" if success else "warning"))
    email_ok = _send_email(f"[meeting_record] {title}", f"{title}\n\n{body}".strip())
    if slack_ok or email_ok:
        channels = []
        if slack_ok: channels.append("Slack")
        if email_ok: channels.append("이메일")
        print(f"    [알림] {', '.join(channels)} 전송")
    return slack_ok or email_ok


def is_configured() -> dict:
    """현재 알림 설정 상태 반환 (doctor.py에서 호출)."""
    return {
        "level": _level(),
        "slack": bool(_env("NOTIFY_SLACK_WEBHOOK")),
        "email": bool(_env("NOTIFY_EMAIL_HOST") and _env("NOTIFY_EMAIL_USER") and _env("NOTIFY_EMAIL_TO")),
    }
