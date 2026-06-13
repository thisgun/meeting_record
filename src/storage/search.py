"""FTS5 전문 검색 (회의/발화)."""
from __future__ import annotations

import re

from .db import connect


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
