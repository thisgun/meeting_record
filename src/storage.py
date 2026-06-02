"""SQLite 저장소.

스키마:
- meetings: 회의 단위 메타 + 요약
- utterances: 회의별 발화 (화자/타임스탬프/텍스트)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

-- FTS5 전문 검색 인덱스 (한국어 트라이그램 토크나이저)
CREATE VIRTUAL TABLE IF NOT EXISTS meetings_fts USING fts5(
    title, summary_md,
    content='meetings', content_rowid='id',
    tokenize='trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS utterances_fts USING fts5(
    text, speaker,
    content='utterances', content_rowid='id',
    tokenize='trigram'
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


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


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
    speakers = sorted({u["speaker"] for u in utterances})

    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO meetings
                 (created_at, source_file, title, summary_md, duration_sec, speaker_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (now, str(source_file), title, summary_md, float(duration_sec), len(speakers)),
        )
        meeting_id = cur.lastrowid
        conn.executemany(
            """INSERT INTO utterances
                 (meeting_id, seq, speaker, start_sec, end_sec, text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
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
        return {
            "meeting": dict(row),
            "utterances": [dict(u) for u in utts],
        }


def list_unsynced(db_path: str | Path) -> list[dict]:
    """remote 업로드 실패/대기 중인 회의."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM meetings WHERE sync_status IN ('pending', 'failed') ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_meeting_synced(
    db_path: str | Path, meeting_id: int, remote_post_id: str
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE meetings
                 SET sync_status = 'synced', remote_post_id = ?, sync_error = NULL
               WHERE id = ?""",
            (remote_post_id, meeting_id),
        )


def mark_meeting_failed(
    db_path: str | Path, meeting_id: int, error: str
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE meetings SET sync_status = 'failed', sync_error = ? WHERE id = ?",
            (error[:2000], meeting_id),
        )


def mark_utterance_synced(
    db_path: str | Path, utterance_id: int, remote_comment_id: str
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE utterances
                 SET sync_status = 'synced', remote_comment_id = ?
               WHERE id = ?""",
            (remote_comment_id, utterance_id),
        )


def search_meetings(
    db_path,
    query: str,
    *,
    limit: int = 20,
    since: str | None = None,
    until: str | None = None,
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
    params: list = [query]
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
    params: list = [query]
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
