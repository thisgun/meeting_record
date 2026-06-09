"""원격(그누보드) 동기화 멱등성 키 생성 — 재시도 시 중복 게시/댓글 방지."""
from __future__ import annotations


def _safe_key_part(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    return "".join(ch if ch in allowed else "_" for ch in str(value or "").lower())


def _remote_idempotency_key(
    kind: str,
    meeting_uuid: str,
    target_name: str,
    *,
    utterance_uuid: str | None = None,
) -> str:
    meeting_ref = _safe_key_part(meeting_uuid)
    target = _safe_key_part(target_name or "default")
    if not meeting_ref:
        raise ValueError("meeting_uuid is required for remote idempotency")
    if utterance_uuid is None:
        return f"meeting_record:{kind}:{meeting_ref}:{target}"
    utterance_ref = _safe_key_part(utterance_uuid)
    if not utterance_ref:
        raise ValueError("utterance_uuid is required for comment idempotency")
    return f"meeting_record:{kind}:{meeting_ref}:{utterance_ref}:{target}"
