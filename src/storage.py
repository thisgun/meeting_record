"""SQLite 저장소.

스키마:
- meetings: 회의 단위 메타 + 요약
- utterances: 회의별 발화 (화자/타임스탬프/텍스트)
"""
from __future__ import annotations

import sqlite3
import re
import uuid as uuidlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT,
    created_at TEXT NOT NULL,
    source_file TEXT NOT NULL,
    title TEXT NOT NULL,
    summary_md TEXT NOT NULL,
    duration_sec REAL DEFAULT 0,
    speaker_count INTEGER DEFAULT 0,
    remote_post_id TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending',
    sync_error TEXT
);

CREATE TABLE IF NOT EXISTS utterances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    speaker TEXT NOT NULL,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    text TEXT NOT NULL,
    remote_comment_id TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_utt_meeting ON utterances(meeting_id, seq);
CREATE INDEX IF NOT EXISTS idx_meetings_sync ON meetings(sync_status);

CREATE TABLE IF NOT EXISTS meeting_sync_targets (
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    target_name TEXT NOT NULL,
    remote_post_id TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending',
    sync_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (meeting_id, target_name)
);

CREATE TABLE IF NOT EXISTS utterance_sync_targets (
    utterance_id INTEGER NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
    target_name TEXT NOT NULL,
    remote_comment_id TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending',
    sync_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (utterance_id, target_name)
);

CREATE INDEX IF NOT EXISTS idx_meeting_targets_status
    ON meeting_sync_targets(target_name, sync_status);
CREATE INDEX IF NOT EXISTS idx_utterance_targets_status
    ON utterance_sync_targets(target_name, sync_status);
"""


FTS_SCHEMA_TEMPLATE = """
-- FTS5 전문 검색 인덱스 (trigram 우선, 미지원 시 unicode61 fallback)
CREATE VIRTUAL TABLE IF NOT EXISTS meetings_fts USING fts5(
    title, summary_md,
    content='meetings', content_rowid='id',
    tokenize='{tokenizer}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS utterances_fts USING fts5(
    text, speaker,
    content='utterances', content_rowid='id',
    tokenize='{tokenizer}'
);

-- meetings ↔ meetings_fts 동기화 트리거
CREATE TRIGGER IF NOT EXISTS meetings_ai AFTER INSERT ON meetings BEGIN
    INSERT INTO meetings_fts(rowid, title, summary_md) VALUES (new.id, new.title, new.summary_md);
END;
CREATE TRIGGER IF NOT EXISTS meetings_ad AFTER DELETE ON meetings BEGIN
    INSERT INTO meetings_fts(meetings_fts, rowid, title, summary_md) VALUES('delete', old.id, old.title, old.summary_md);
END;
CREATE TRIGGER IF NOT EXISTS meetings_au AFTER UPDATE ON meetings BEGIN
    INSERT INTO meetings_fts(meetings_fts, rowid, title, summary_md) VALUES('delete', old.id, old.title, old.summary_md);
    INSERT INTO meetings_fts(rowid, title, summary_md) VALUES (new.id, new.title, new.summary_md);
END;

-- utterances ↔ utterances_fts 동기화 트리거
CREATE TRIGGER IF NOT EXISTS utterances_ai AFTER INSERT ON utterances BEGIN
    INSERT INTO utterances_fts(rowid, text, speaker) VALUES (new.id, new.text, new.speaker);
END;
CREATE TRIGGER IF NOT EXISTS utterances_ad AFTER DELETE ON utterances BEGIN
    INSERT INTO utterances_fts(utterances_fts, rowid, text, speaker) VALUES('delete', old.id, old.text, old.speaker);
END;
CREATE TRIGGER IF NOT EXISTS utterances_au AFTER UPDATE ON utterances BEGIN
    INSERT INTO utterances_fts(utterances_fts, rowid, text, speaker) VALUES('delete', old.id, old.text, old.speaker);
    INSERT INTO utterances_fts(rowid, text, speaker) VALUES (new.id, new.text, new.speaker);
END;
"""


def _fts_schema(tokenizer: str) -> str:
    return FTS_SCHEMA_TEMPLATE.format(tokenizer=tokenizer)


def _ensure_fts_schema(conn: sqlite3.Connection) -> str:
    """Create FTS5 tables, falling back when SQLite lacks the trigram tokenizer."""
    for tokenizer in ("trigram", "unicode61"):
        try:
            conn.executescript(_fts_schema(tokenizer))
            return tokenizer
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if tokenizer == "trigram" and ("tokenizer" in message or "parse error" in message):
                conn.execute("DROP TABLE IF EXISTS meetings_fts")
                conn.execute("DROP TABLE IF EXISTS utterances_fts")
                continue
            raise
    raise sqlite3.OperationalError("Unable to create FTS5 tables")


def rebuild_fts(db_path) -> None:
    """기존 데이터를 FTS5 인덱스에 백필 (1회 마이그레이션 또는 인덱스 깨졌을 때)."""
    with connect(db_path) as conn:
        conn.execute("INSERT INTO meetings_fts(meetings_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO utterances_fts(utterances_fts) VALUES('rebuild')")


@contextmanager
def connect(db_path: str | Path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _backfill_uuid_column(conn: sqlite3.Connection, table_name: str) -> None:
    for row in conn.execute(
        f"SELECT id FROM {table_name} WHERE uuid IS NULL OR uuid = ''"
    ).fetchall():
        conn.execute(
            f"UPDATE {table_name} SET uuid = ? WHERE id = ?",
            (str(uuidlib.uuid4()), int(row["id"])),
        )


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(BASE_SCHEMA)
        _ensure_fts_schema(conn)
        _ensure_column(conn, "meetings", "uuid", "TEXT")
        _ensure_column(conn, "utterances", "uuid", "TEXT")
        _backfill_uuid_column(conn, "meetings")
        _backfill_uuid_column(conn, "utterances")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_uuid ON meetings(uuid)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_utterances_uuid ON utterances(uuid)")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """INSERT OR IGNORE INTO meeting_sync_targets
                 (meeting_id, target_name, remote_post_id, sync_status, sync_error, updated_at)
               SELECT id, 'default', remote_post_id, sync_status, sync_error, ?
                 FROM meetings
                WHERE remote_post_id IS NOT NULL AND remote_post_id <> ''""",
            (now,),
        )
        conn.execute(
            """INSERT OR IGNORE INTO utterance_sync_targets
                 (utterance_id, target_name, remote_comment_id, sync_status, sync_error, updated_at)
               SELECT id, 'default', remote_comment_id, sync_status, NULL, ?
                 FROM utterances
                WHERE remote_comment_id IS NOT NULL AND remote_comment_id <> ''""",
            (now,),
        )


def save_meeting(
    db_path: str | Path,
    *,
    source_file: str,
    title: str,
    summary_md: str,
    duration_sec: float,
    utterances: list[dict],
) -> int:
    """회의 + 발화 저장. meeting_id 반환."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meeting_uuid = str(uuidlib.uuid4())
    speakers = sorted({u["speaker"] for u in utterances})

    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO meetings
                 (uuid, created_at, source_file, title, summary_md, duration_sec, speaker_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (meeting_uuid, now, str(source_file), title, summary_md, float(duration_sec), len(speakers)),
        )
        meeting_id = cur.lastrowid
        conn.executemany(
            """INSERT INTO utterances
                 (uuid, meeting_id, seq, speaker, start_sec, end_sec, text)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    str(uuidlib.uuid4()),
                    meeting_id, i,
                    u["speaker"],
                    float(u["start"]), float(u["end"]),
                    u["text"],
                )
                for i, u in enumerate(utterances)
            ],
        )
    return meeting_id


def get_meeting(db_path: str | Path, meeting_id: int) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        if not row:
            return None
        utts = conn.execute(
            "SELECT * FROM utterances WHERE meeting_id = ? ORDER BY seq",
            (meeting_id,),
        ).fetchall()
        targets = conn.execute(
            f"""SELECT * FROM meeting_sync_targets
                  WHERE meeting_id = ?
                  ORDER BY {_target_order_sql()}""",
            (meeting_id,),
        ).fetchall()
        utt_targets = conn.execute(
            """SELECT ust.*
                 FROM utterance_sync_targets ust
                 JOIN utterances u ON u.id = ust.utterance_id
                WHERE u.meeting_id = ?
                ORDER BY u.seq, ust.target_name""",
            (meeting_id,),
        ).fetchall()
        by_utt: dict[int, list[dict]] = {}
        for target in utt_targets:
            item = dict(target)
            by_utt.setdefault(int(item["utterance_id"]), []).append(item)

        utterances = []
        for u in utts:
            item = dict(u)
            item["sync_targets"] = by_utt.get(int(item["id"]), [])
            utterances.append(item)
        return {
            "meeting": dict(row),
            "sync_targets": [dict(t) for t in targets],
            "utterances": utterances,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _target_order_sql() -> str:
    return "CASE WHEN target_name = 'default' THEN 0 ELSE 1 END, updated_at, target_name"


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
        for row in rows:
            target_rows = {
                r["target_name"]: dict(r)
                for r in conn.execute(
                    "SELECT * FROM meeting_sync_targets WHERE meeting_id = ?",
                    (row["id"],),
                ).fetchall()
            }
            if any(target_rows.get(name, {}).get("sync_status") != "synced" for name in wanted):
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


def list_meetings(db_path, *, limit: int = 100) -> list[dict]:
    """전체 회의 목록 (최신순)."""
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            """SELECT m.id, m.created_at, m.title, m.duration_sec, m.speaker_count,
                      m.remote_post_id, m.sync_status,
                      (SELECT COUNT(*) FROM utterances u WHERE u.meeting_id = m.id) AS utterance_count
               FROM meetings m ORDER BY m.id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()]


def update_utterance_text(db_path, utterance_id: int, new_text: str) -> bool:
    """발화 텍스트 수정 (FTS 자동 동기화)."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE utterances SET text = ? WHERE id = ?",
            (new_text, int(utterance_id)),
        )
        return cur.rowcount > 0


def update_speaker_label(db_path, meeting_id: int, old_label: str, new_label: str) -> int:
    """meeting 내의 화자 라벨 일괄 변경 (예: '사용자3' → '장관님'). 변경된 발화 수 반환."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE utterances SET speaker = ? WHERE meeting_id = ? AND speaker = ?",
            (new_label, int(meeting_id), old_label),
        )
        return cur.rowcount


def update_meeting_summary(db_path, meeting_id: int, *, title: str | None = None, summary_md: str | None = None) -> None:
    fields = []
    params: list = []
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    if summary_md is not None:
        fields.append("summary_md = ?")
        params.append(summary_md)
    if not fields:
        return
    params.extend([int(meeting_id)])
    with connect(db_path) as conn:
        conn.execute(f"UPDATE meetings SET {', '.join(fields)} WHERE id = ?", params)


def delete_meeting(db_path, meeting_id: int) -> bool:
    """회의 + 발화 일괄 삭제 (CASCADE)."""
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM meetings WHERE id = ?", (int(meeting_id),))
        return cur.rowcount > 0


def _fts_query(query: str, *, advanced: bool = False) -> str:
    query = (query or "").strip()
    if advanced:
        return query
    parts = [p for p in re.split(r"\s+", query) if p]
    if not parts:
        return '""'
    return " AND ".join('"' + p.replace('"', '""') + '"' for p in parts)


def search_meetings(
    db_path,
    query: str,
    *,
    limit: int = 20,
    since: str | None = None,
    until: str | None = None,
    advanced: bool = False,
) -> list[dict]:
    """회의 제목/요약 본문 검색.

    query: FTS5 MATCH 쿼리 (예: "산재 OR 중대재해", "안전 NEAR/5 점검")
    since/until: ISO date (예: '2026-01-01')
    """
    sql = """
    SELECT m.id, m.created_at, m.title,
           snippet(meetings_fts, 1, '【', '】', '...', 32) AS snippet,
           bm25(meetings_fts) AS score
    FROM meetings_fts
    JOIN meetings m ON m.id = meetings_fts.rowid
    WHERE meetings_fts MATCH ?
    """
    params: list = [_fts_query(query, advanced=advanced)]
    if since:
        sql += " AND m.created_at >= ?"
        params.append(since)
    if until:
        sql += " AND m.created_at <= ?"
        params.append(until)
    sql += " ORDER BY score LIMIT ?"
    params.append(int(limit))

    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def search_utterances(
    db_path,
    query: str,
    *,
    speaker: str | None = None,
    meeting_id: int | None = None,
    limit: int = 50,
    advanced: bool = False,
) -> list[dict]:
    """발화 검색.

    query: FTS5 MATCH 쿼리
    speaker: 화자명 정확 일치 필터 (예: '사용자3' 또는 '회의_사용자3')
    meeting_id: 특정 회의만 검색
    """
    sql = """
    SELECT u.id, u.meeting_id, u.speaker, u.start_sec, u.end_sec,
           snippet(utterances_fts, 0, '【', '】', '...', 32) AS snippet,
           m.title AS meeting_title,
           bm25(utterances_fts) AS score
    FROM utterances_fts
    JOIN utterances u ON u.id = utterances_fts.rowid
    JOIN meetings m ON m.id = u.meeting_id
    WHERE utterances_fts MATCH ?
    """
    params: list = [_fts_query(query, advanced=advanced)]
    if speaker:
        sql += " AND u.speaker = ?"
        params.append(speaker)
    if meeting_id:
        sql += " AND u.meeting_id = ?"
        params.append(int(meeting_id))
    sql += " ORDER BY score LIMIT ?"
    params.append(int(limit))

    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


if __name__ == "__main__":
    db = "./data/meetings.db"
    init_db(db)
    mid = save_meeting(
        db,
        source_file="dummy.m4a",
        title="테스트 회의",
        summary_md="## 개요\n테스트입니다.",
        duration_sec=12.3,
        utterances=[
            {"speaker": "사용자1", "start": 0.0, "end": 2.0, "text": "안녕하세요."},
            {"speaker": "사용자2", "start": 2.5, "end": 4.0, "text": "반갑습니다."},
        ],
    )
    print(f"saved meeting_id={mid}")
    print(get_meeting(db, mid))
