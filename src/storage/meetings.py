"""회의/발화 CRUD."""
from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path

from .db import _target_order_sql, connect, init_db


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
