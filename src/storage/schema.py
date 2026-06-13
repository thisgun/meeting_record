"""SQLite 스키마 상수 (테이블/FTS5 인덱스/트리거)."""
from __future__ import annotations


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


FTS_TRIGGER_NAMES = (
    "meetings_ai",
    "meetings_ad",
    "meetings_au",
    "utterances_ai",
    "utterances_ad",
    "utterances_au",
)
