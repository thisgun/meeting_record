"""저수준 DB 기반: 연결, 시각/정렬 헬퍼, 스키마·마이그레이션, FTS5 관리."""
from __future__ import annotations

import sqlite3
import uuid as uuidlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schema import BASE_SCHEMA, FTS_SCHEMA_TEMPLATE, FTS_TRIGGER_NAMES


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _target_order_sql() -> str:
    return "CASE WHEN target_name = 'default' THEN 0 ELSE 1 END, updated_at, target_name"


# ── FTS5 스키마 관리 ──────────────────────────────────────────
def _fts_schema(tokenizer: str) -> str:
    return FTS_SCHEMA_TEMPLATE.format(tokenizer=tokenizer)


def _parse_fts_tokenizer(sql: str | None) -> str | None:
    sql = (sql or "").lower()
    if "tokenize='trigram'" in sql or 'tokenize="trigram"' in sql or "tokenize=trigram" in sql:
        return "trigram"
    if "tokenize='unicode61'" in sql or 'tokenize="unicode61"' in sql or "tokenize=unicode61" in sql:
        return "unicode61"
    return None


def _existing_fts_tokenizer(conn: sqlite3.Connection) -> str | None:
    rows = conn.execute(
        """SELECT name, sql
             FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('meetings_fts', 'utterances_fts')"""
    ).fetchall()
    if len(rows) != 2:
        return None
    tokenizers = {_parse_fts_tokenizer(row["sql"]) or "unknown" for row in rows}
    if len(tokenizers) == 1:
        return tokenizers.pop()
    return "mixed"


def _ensure_fts_schema(conn: sqlite3.Connection) -> str:
    """Create FTS5 tables, falling back when SQLite lacks the trigram tokenizer."""
    existing = _existing_fts_tokenizer(conn)
    if existing:
        return existing
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


def _drop_fts_schema(conn: sqlite3.Connection) -> None:
    for trigger_name in FTS_TRIGGER_NAMES:
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    conn.execute("DROP TABLE IF EXISTS meetings_fts")
    conn.execute("DROP TABLE IF EXISTS utterances_fts")


def get_fts_info(db_path: str | Path) -> dict:
    """Return SQLite FTS capability details for diagnostics."""
    with connect(db_path) as conn:
        conn.executescript(BASE_SCHEMA)
        tokenizer = _ensure_fts_schema(conn)
        version = conn.execute("SELECT sqlite_version() AS version").fetchone()["version"]
        return {
            "sqlite_version": version,
            "tokenizer": tokenizer,
        }


def recreate_fts(db_path: str | Path, *, tokenizer: str = "auto") -> str:
    """Drop and recreate FTS5 tables/triggers, then rebuild existing data."""
    tokenizer = (tokenizer or "auto").strip().lower()
    if tokenizer not in ("auto", "trigram", "unicode61"):
        raise ValueError("tokenizer must be one of: auto, trigram, unicode61")

    with connect(db_path) as conn:
        conn.executescript(BASE_SCHEMA)
        _drop_fts_schema(conn)
        if tokenizer == "auto":
            actual = _ensure_fts_schema(conn)
        else:
            conn.executescript(_fts_schema(tokenizer))
            actual = tokenizer
        conn.execute("INSERT INTO meetings_fts(meetings_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO utterances_fts(utterances_fts) VALUES('rebuild')")
        return actual


def rebuild_fts(db_path) -> None:
    """기존 데이터를 FTS5 인덱스에 백필 (1회 마이그레이션 또는 인덱스 깨졌을 때)."""
    with connect(db_path) as conn:
        conn.execute("INSERT INTO meetings_fts(meetings_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO utterances_fts(utterances_fts) VALUES('rebuild')")


# ── 컬럼 마이그레이션 ─────────────────────────────────────────
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
