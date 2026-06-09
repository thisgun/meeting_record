"""그누보드5 업로드 동기화 상태 (멀티 타겟·rollup·재시도 목록)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import _target_order_sql, _utc_now, connect, init_db


def _rollup_meeting(conn: sqlite3.Connection, meeting_id: int, *, primary_post_id: str | None = None) -> None:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM meeting_sync_targets WHERE meeting_id = ?",
        (int(meeting_id),),
    ).fetchall()]
    if not rows:
        return

    statuses = [r["sync_status"] for r in rows]
    post_id = primary_post_id or next((r["remote_post_id"] for r in sorted(
        rows,
        key=lambda r: (0 if r["target_name"] == "default" else 1, r["updated_at"], r["target_name"]),
    ) if r.get("remote_post_id")), None)
    errors = [f"{r['target_name']}: {r['sync_error']}" for r in rows if r.get("sync_error")]

    if all(s == "synced" for s in statuses):
        status = "synced"
    elif any(s in ("synced", "partial") for s in statuses) or post_id:
        status = "partial"
    elif any(s == "failed" for s in statuses):
        status = "failed"
    else:
        status = "pending"

    conn.execute(
        """UPDATE meetings
              SET sync_status = ?, remote_post_id = COALESCE(?, remote_post_id), sync_error = ?
            WHERE id = ?""",
        (status, post_id, "; ".join(errors)[:2000] if errors else None, int(meeting_id)),
    )


def _rollup_utterance(conn: sqlite3.Connection, utterance_id: int, *, primary_comment_id: str | None = None) -> None:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM utterance_sync_targets WHERE utterance_id = ?",
        (int(utterance_id),),
    ).fetchall()]
    if not rows:
        return

    statuses = [r["sync_status"] for r in rows]
    comment_id = primary_comment_id or next((r["remote_comment_id"] for r in sorted(
        rows,
        key=lambda r: (0 if r["target_name"] == "default" else 1, r["updated_at"], r["target_name"]),
    ) if r.get("remote_comment_id")), None)
    if all(s == "synced" for s in statuses):
        status = "synced"
    elif any(s == "synced" for s in statuses):
        status = "partial"
    elif any(s == "failed" for s in statuses):
        status = "failed"
    else:
        status = "pending"

    conn.execute(
        """UPDATE utterances
              SET sync_status = ?, remote_comment_id = COALESCE(?, remote_comment_id)
            WHERE id = ?""",
        (status, comment_id, int(utterance_id)),
    )


def _upsert_meeting_target(
    conn: sqlite3.Connection,
    meeting_id: int,
    target_name: str,
    *,
    remote_post_id: str | None,
    sync_status: str,
    sync_error: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO meeting_sync_targets
             (meeting_id, target_name, remote_post_id, sync_status, sync_error, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(meeting_id, target_name) DO UPDATE SET
             remote_post_id = COALESCE(excluded.remote_post_id, meeting_sync_targets.remote_post_id),
             sync_status = excluded.sync_status,
             sync_error = excluded.sync_error,
             updated_at = excluded.updated_at""",
        (
            int(meeting_id),
            target_name,
            str(remote_post_id) if remote_post_id is not None else None,
            sync_status,
            sync_error[:2000] if sync_error else None,
            _utc_now(),
        ),
    )


def _upsert_utterance_target(
    conn: sqlite3.Connection,
    utterance_id: int,
    target_name: str,
    *,
    remote_comment_id: str | None,
    sync_status: str,
    sync_error: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO utterance_sync_targets
             (utterance_id, target_name, remote_comment_id, sync_status, sync_error, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(utterance_id, target_name) DO UPDATE SET
             remote_comment_id = COALESCE(excluded.remote_comment_id, utterance_sync_targets.remote_comment_id),
             sync_status = excluded.sync_status,
             sync_error = excluded.sync_error,
             updated_at = excluded.updated_at""",
        (
            int(utterance_id),
            target_name,
            str(remote_comment_id) if remote_comment_id is not None else None,
            sync_status,
            sync_error[:2000] if sync_error else None,
            _utc_now(),
        ),
    )


def _refresh_meeting_target_from_utterances(
    conn: sqlite3.Connection,
    meeting_id: int,
    target_name: str,
) -> None:
    target = conn.execute(
        "SELECT * FROM meeting_sync_targets WHERE meeting_id = ? AND target_name = ?",
        (int(meeting_id), target_name),
    ).fetchone()
    if not target or not target["remote_post_id"]:
        return

    rows = [dict(r) for r in conn.execute(
        """SELECT u.seq, ust.remote_comment_id, ust.sync_status, ust.sync_error
             FROM utterances u
        LEFT JOIN utterance_sync_targets ust
               ON ust.utterance_id = u.id AND ust.target_name = ?
            WHERE u.meeting_id = ?
            ORDER BY u.seq""",
        (target_name, int(meeting_id)),
    ).fetchall()]
    incomplete = [
        r for r in rows
        if not r.get("remote_comment_id") or r.get("sync_status") != "synced"
    ]
    errors = [
        f"seq={r['seq']}: {r['sync_error']}"
        for r in rows
        if r.get("sync_error")
    ]
    status = "partial" if incomplete else "synced"
    if incomplete and not errors:
        errors.append(f"{len(incomplete)} comments pending")

    conn.execute(
        """UPDATE meeting_sync_targets
              SET sync_status = ?, sync_error = ?, updated_at = ?
            WHERE meeting_id = ? AND target_name = ?""",
        (
            status,
            "; ".join(errors)[:2000] if errors else None,
            _utc_now(),
            int(meeting_id),
            target_name,
        ),
    )


def list_unsynced(db_path: str | Path, target_names: list[str] | None = None) -> list[dict]:
    """remote 업로드 실패/대기 중인 회의."""
    with connect(db_path) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM meetings ORDER BY id").fetchall()]
        if not target_names:
            return [r for r in rows if r["sync_status"] in ("pending", "partial", "failed")]

        out: list[dict] = []
        wanted = [t for t in target_names if t]
        retryable_statuses = {"pending", "partial", "failed"}
        for row in rows:
            if row.get("sync_status") == "blocked":
                continue
            target_rows = {
                r["target_name"]: dict(r)
                for r in conn.execute(
                    "SELECT * FROM meeting_sync_targets WHERE meeting_id = ?",
                    (row["id"],),
                ).fetchall()
            }
            if any(target_rows.get(name, {}).get("sync_status", "pending") in retryable_statuses for name in wanted):
                out.append(row)
        return out


def list_meeting_targets(db_path: str | Path, meeting_id: int) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT * FROM meeting_sync_targets
                  WHERE meeting_id = ?
                  ORDER BY {_target_order_sql()}""",
            (int(meeting_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_meeting_target(db_path: str | Path, meeting_id: int, target_name: str) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM meeting_sync_targets WHERE meeting_id = ? AND target_name = ?",
            (int(meeting_id), target_name),
        ).fetchone()
        return dict(row) if row else None


def get_utterance_target(db_path: str | Path, utterance_id: int, target_name: str) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM utterance_sync_targets WHERE utterance_id = ? AND target_name = ?",
            (int(utterance_id), target_name),
        ).fetchone()
        return dict(row) if row else None


def mark_meeting_posted(
    db_path: str | Path,
    meeting_id: int,
    remote_post_id: str,
    *,
    target_name: str = "default",
    primary: bool = True,
) -> None:
    """게시글 생성은 성공했고 댓글 동기화는 진행 중인 상태로 표시."""
    with connect(db_path) as conn:
        _upsert_meeting_target(
            conn, meeting_id, target_name,
            remote_post_id=remote_post_id, sync_status="partial", sync_error=None,
        )
        _rollup_meeting(conn, meeting_id, primary_post_id=str(remote_post_id) if primary else None)


def mark_meeting_synced(
    db_path: str | Path,
    meeting_id: int,
    remote_post_id: str,
    *,
    target_name: str = "default",
    primary: bool = True,
) -> None:
    with connect(db_path) as conn:
        _upsert_meeting_target(
            conn, meeting_id, target_name,
            remote_post_id=remote_post_id, sync_status="synced", sync_error=None,
        )
        _rollup_meeting(conn, meeting_id, primary_post_id=str(remote_post_id) if primary else None)


def mark_meeting_post_updated(
    db_path: str | Path,
    meeting_id: int,
    remote_post_id: str,
    *,
    target_name: str = "default",
    primary: bool = True,
) -> None:
    """게시글 본문/제목 업데이트 성공. 댓글 상태를 반영해 타겟 상태를 재계산한다."""
    with connect(db_path) as conn:
        _upsert_meeting_target(
            conn, meeting_id, target_name,
            remote_post_id=remote_post_id, sync_status="synced", sync_error=None,
        )
        _refresh_meeting_target_from_utterances(conn, meeting_id, target_name)
        _rollup_meeting(conn, meeting_id, primary_post_id=str(remote_post_id) if primary else None)


def mark_meeting_partial(
    db_path: str | Path,
    meeting_id: int,
    remote_post_id: str,
    error: str,
    *,
    target_name: str = "default",
    primary: bool = True,
) -> None:
    """게시글은 있으나 일부 댓글 동기화가 남아 있는 상태."""
    with connect(db_path) as conn:
        _upsert_meeting_target(
            conn, meeting_id, target_name,
            remote_post_id=remote_post_id, sync_status="partial", sync_error=error,
        )
        _rollup_meeting(conn, meeting_id, primary_post_id=str(remote_post_id) if primary else None)


def mark_meeting_failed(
    db_path: str | Path,
    meeting_id: int,
    error: str,
    *,
    target_name: str | None = None,
) -> None:
    with connect(db_path) as conn:
        if target_name:
            _upsert_meeting_target(
                conn, meeting_id, target_name,
                remote_post_id=None, sync_status="failed", sync_error=error,
            )
            _rollup_meeting(conn, meeting_id)
        else:
            conn.execute(
                "UPDATE meetings SET sync_status = 'failed', sync_error = ? WHERE id = ?",
                (error[:2000], int(meeting_id)),
            )


def mark_meeting_upload_blocked(
    db_path: str | Path,
    meeting_id: int,
    error: str,
    *,
    target_names: list[str] | None = None,
) -> None:
    """Mark a meeting as intentionally not uploaded by the quality gate."""
    init_db(db_path)
    target_names = [name for name in (target_names or []) if name]
    with connect(db_path) as conn:
        for target_name in target_names:
            _upsert_meeting_target(
                conn,
                meeting_id,
                target_name,
                remote_post_id=None,
                sync_status="blocked",
                sync_error=error,
            )
        conn.execute(
            "UPDATE meetings SET sync_status = 'blocked', sync_error = ? WHERE id = ?",
            (error[:2000], int(meeting_id)),
        )


def mark_utterance_synced(
    db_path: str | Path,
    utterance_id: int,
    remote_comment_id: str,
    *,
    target_name: str = "default",
    primary: bool = True,
) -> None:
    with connect(db_path) as conn:
        _upsert_utterance_target(
            conn, utterance_id, target_name,
            remote_comment_id=remote_comment_id, sync_status="synced", sync_error=None,
        )
        _rollup_utterance(conn, utterance_id, primary_comment_id=str(remote_comment_id) if primary else None)
        parent = conn.execute(
            "SELECT meeting_id FROM utterances WHERE id = ?",
            (int(utterance_id),),
        ).fetchone()
        if parent:
            meeting_id = int(parent["meeting_id"])
            _refresh_meeting_target_from_utterances(conn, meeting_id, target_name)
            _rollup_meeting(conn, meeting_id)


def mark_utterance_failed(
    db_path: str | Path,
    utterance_id: int,
    error: str,
    *,
    target_name: str = "default",
) -> None:
    with connect(db_path) as conn:
        _upsert_utterance_target(
            conn, utterance_id, target_name,
            remote_comment_id=None, sync_status="failed", sync_error=error,
        )
        _rollup_utterance(conn, utterance_id)
        parent = conn.execute(
            "SELECT meeting_id FROM utterances WHERE id = ?",
            (int(utterance_id),),
        ).fetchone()
        if parent:
            meeting_id = int(parent["meeting_id"])
            _refresh_meeting_target_from_utterances(conn, meeting_id, target_name)
            _rollup_meeting(conn, meeting_id)


def adopt_default_sync_target(db_path: str | Path, target_name: str) -> tuple[int, int]:
    """기존 단일 타겟(default) 동기화 정보를 새 단일 타겟명으로 복사한다."""
    target_name = (target_name or "").strip()
    if not target_name or target_name == "default":
        return (0, 0)
    init_db(db_path)
    with connect(db_path) as conn:
        now = _utc_now()
        meeting_insert = conn.execute(
            """INSERT OR IGNORE INTO meeting_sync_targets
                 (meeting_id, target_name, remote_post_id, sync_status, sync_error, updated_at)
               SELECT meeting_id, ?, remote_post_id, sync_status, sync_error, ?
                 FROM meeting_sync_targets
                WHERE target_name = 'default'
                  AND remote_post_id IS NOT NULL
                  AND remote_post_id <> ''""",
            (target_name, now),
        )
        meeting_update = conn.execute(
            """UPDATE meeting_sync_targets
                  SET remote_post_id = (
                          SELECT src.remote_post_id
                            FROM meeting_sync_targets src
                           WHERE src.meeting_id = meeting_sync_targets.meeting_id
                             AND src.target_name = 'default'
                      ),
                      sync_status = (
                          SELECT src.sync_status
                            FROM meeting_sync_targets src
                           WHERE src.meeting_id = meeting_sync_targets.meeting_id
                             AND src.target_name = 'default'
                      ),
                      sync_error = (
                          SELECT src.sync_error
                            FROM meeting_sync_targets src
                           WHERE src.meeting_id = meeting_sync_targets.meeting_id
                             AND src.target_name = 'default'
                      ),
                      updated_at = ?
                WHERE target_name = ?
                  AND (remote_post_id IS NULL OR remote_post_id = '')
                  AND EXISTS (
                      SELECT 1
                        FROM meeting_sync_targets src
                       WHERE src.meeting_id = meeting_sync_targets.meeting_id
                         AND src.target_name = 'default'
                         AND src.remote_post_id IS NOT NULL
                         AND src.remote_post_id <> ''
                  )""",
            (now, target_name),
        )
        utterance_insert = conn.execute(
            """INSERT OR IGNORE INTO utterance_sync_targets
                 (utterance_id, target_name, remote_comment_id, sync_status, sync_error, updated_at)
               SELECT utterance_id, ?, remote_comment_id, sync_status, sync_error, ?
                 FROM utterance_sync_targets
                WHERE target_name = 'default'
                  AND remote_comment_id IS NOT NULL
                  AND remote_comment_id <> ''""",
            (target_name, now),
        )
        utterance_update = conn.execute(
            """UPDATE utterance_sync_targets
                  SET remote_comment_id = (
                          SELECT src.remote_comment_id
                            FROM utterance_sync_targets src
                           WHERE src.utterance_id = utterance_sync_targets.utterance_id
                             AND src.target_name = 'default'
                      ),
                      sync_status = (
                          SELECT src.sync_status
                            FROM utterance_sync_targets src
                           WHERE src.utterance_id = utterance_sync_targets.utterance_id
                             AND src.target_name = 'default'
                      ),
                      sync_error = (
                          SELECT src.sync_error
                            FROM utterance_sync_targets src
                           WHERE src.utterance_id = utterance_sync_targets.utterance_id
                             AND src.target_name = 'default'
                      ),
                      updated_at = ?
                WHERE target_name = ?
                  AND (remote_comment_id IS NULL OR remote_comment_id = '')
                  AND EXISTS (
                      SELECT 1
                        FROM utterance_sync_targets src
                       WHERE src.utterance_id = utterance_sync_targets.utterance_id
                         AND src.target_name = 'default'
                         AND src.remote_comment_id IS NOT NULL
                         AND src.remote_comment_id <> ''
                  )""",
            (now, target_name),
        )
        meetings = max(meeting_insert.rowcount, 0) + max(meeting_update.rowcount, 0)
        utterances = max(utterance_insert.rowcount, 0) + max(utterance_update.rowcount, 0)
        return (meetings, utterances)
