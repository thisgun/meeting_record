"""게시판 워처 상태 테이블(qa_answers, moderation)을 meetings.db → board.db로 이전.

도메인 분리: meetings.db는 회의록 전용(meetings/utterances/FTS/sync/rag_chunks),
board.db는 게시판 워처 상태(qa_answers/moderation)를 담는다.

기존 meetings.db에 두 테이블이 있으면 board.db로 복사하고, 원본은 보존한다
(검증 후 수동 삭제 가능). 여러 번 실행해도 안전(INSERT OR IGNORE).

사용: python scripts/migrate_board_tables.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_config  # noqa: E402

TABLES = ("qa_answers", "moderation")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def migrate(src_db: Path, dst_db: Path) -> None:
    if not src_db.exists():
        print(f"원본 DB 없음: {src_db} — 이전할 것이 없습니다.")
        return
    src = sqlite3.connect(str(src_db))
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(dst_db))
    try:
        for table in TABLES:
            if not _has_table(src, table):
                print(f"[{table}] 원본에 없음 — 건너뜀")
                continue
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"[{table}] 행 없음 — 건너뜀")
                continue
            # 원본 테이블의 CREATE 문을 그대로 board.db에 생성
            ddl = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            dst.execute(ddl)
            cols = [d[0] for d in src.execute(f"SELECT * FROM {table} LIMIT 1").description]
            placeholders = ",".join("?" * len(cols))
            collist = ",".join(cols)
            dst.executemany(
                f"INSERT OR IGNORE INTO {table} ({collist}) VALUES ({placeholders})",
                [tuple(r) for r in rows],
            )
            dst.commit()
            moved = dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"[{table}] {len(rows)}행 이전 → board.db 총 {moved}행")
    finally:
        src.close()
        dst.close()
    print(f"\n완료. 원본({src_db.name})의 테이블은 보존됨 — 검증 후 수동 삭제 가능.")


if __name__ == "__main__":
    cfg = load_config()
    print(f"이전: {cfg.db_path} → {cfg.board_db_path}")
    migrate(Path(cfg.db_path), Path(cfg.board_db_path))
