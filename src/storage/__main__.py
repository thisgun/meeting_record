"""python -m src.storage 데모 (간단 저장/조회)."""
from __future__ import annotations

from .db import init_db
from .meetings import get_meeting, save_meeting

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
