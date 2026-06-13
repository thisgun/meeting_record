"""SQLite 저장소 패키지.

1012줄 단일 모듈을 역할별로 분리:
- schema:   테이블/FTS 스키마 상수
- db:       연결·시각 헬퍼·마이그레이션·FTS5 관리 (기반)
- meetings: 회의/발화 CRUD
- sync:     그누보드 업로드 동기화 상태 (멀티 타겟·rollup)
- search:   FTS5 전문 검색

기존 코드 호환: `from src import storage` 후 `storage.save_meeting(...)`,
`storage.search_meetings(...)`, `storage.mark_meeting_synced(...)` 등이 그대로 동작한다.
"""
from __future__ import annotations

from .schema import BASE_SCHEMA, FTS_SCHEMA_TEMPLATE, FTS_TRIGGER_NAMES
from .db import (
    _backfill_uuid_column,
    _drop_fts_schema,
    _ensure_column,
    _ensure_fts_schema,
    _existing_fts_tokenizer,
    _fts_schema,
    _parse_fts_tokenizer,
    _table_columns,
    _target_order_sql,
    _utc_now,
    connect,
    get_fts_info,
    init_db,
    rebuild_fts,
    recreate_fts,
)
from .meetings import (
    delete_meeting,
    get_meeting,
    list_meetings,
    save_meeting,
    update_meeting_summary,
    update_speaker_label,
    update_utterance_text,
)
from .sync import (
    _refresh_meeting_target_from_utterances,
    _rollup_meeting,
    _rollup_utterance,
    _upsert_meeting_target,
    _upsert_utterance_target,
    adopt_default_sync_target,
    approve_blocked_meeting,
    get_meeting_target,
    get_utterance_target,
    list_meeting_targets,
    list_unsynced,
    mark_meeting_failed,
    mark_meeting_partial,
    mark_meeting_post_updated,
    mark_meeting_posted,
    mark_meeting_synced,
    mark_meeting_upload_blocked,
    mark_utterance_failed,
    mark_utterance_synced,
)
from .search import _fts_query, search_meetings, search_utterances

__all__ = [
    # 스키마/연결
    "connect", "init_db", "get_fts_info", "recreate_fts", "rebuild_fts",
    # 회의 CRUD
    "save_meeting", "get_meeting", "list_meetings", "delete_meeting",
    "update_meeting_summary", "update_speaker_label", "update_utterance_text",
    # 동기화
    "list_unsynced", "list_meeting_targets", "get_meeting_target", "get_utterance_target",
    "mark_meeting_posted", "mark_meeting_synced", "mark_meeting_post_updated",
    "mark_meeting_partial", "mark_meeting_failed", "mark_meeting_upload_blocked",
    "mark_utterance_synced", "mark_utterance_failed", "adopt_default_sync_target",
    "approve_blocked_meeting",
    # 검색
    "search_meetings", "search_utterances",
]
