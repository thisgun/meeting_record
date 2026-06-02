"""기존 그누보드5 댓글의 작성자명을 화자별로 일괄 업데이트.

사용:
    python scripts/update_comment_authors.py <meeting_id>

meeting_id의 발화 정보(SQLite)와 remote_post_id(그누보드5 wr_id)를 매핑해서
그누보드5 댓글들의 wr_name을 "회의_사용자N"으로 변경한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3

from config import load_config
from src import storage


def main(meeting_id: int) -> int:
    cfg = load_config()

    # 1) SQLite에서 발화 + 메타 정보 가져오기
    meeting = storage.get_meeting(cfg.db_path, meeting_id)
    if not meeting:
        print(f"meeting_id={meeting_id} 없음", file=sys.stderr)
        return 1

    parent_wr_id = meeting["meeting"]["remote_post_id"]
    if not parent_wr_id:
        print(f"meeting_id={meeting_id}는 그누보드5에 업로드 안 됨", file=sys.stderr)
        return 2
    parent_wr_id = int(parent_wr_id)
    utterances = meeting["utterances"]
    print(f"meeting_id={meeting_id}, parent wr_id={parent_wr_id}, 발화 {len(utterances)}건")

    # 2) MariaDB(metting DB)에 직접 연결해서 wr_name 일괄 업데이트
    #    그누보드5 그누보드5의 댓글 → utterances의 seq 순서 매핑
    try:
        import mysql.connector  # type: ignore
    except ImportError:
        # mysql-connector 없으면 PyMySQL 또는 mariadb 시도, 다 없으면 mysql 명령 사용
        return _update_via_mysql_cli(parent_wr_id, utterances)
    return _update_via_python(parent_wr_id, utterances)


def _update_via_mysql_cli(parent_wr_id: int, utterances: list[dict]) -> int:
    """mysql.exe로 SQL 직접 실행."""
    import subprocess
    import tempfile

    # 그누보드5의 댓글 wr_id 가져오기 (시간순)
    mysql = r"C:\xampp\mysql\bin\mysql.exe"
    fetch = subprocess.run(
        [mysql, "-u", "root", "metting", "-N", "-B", "-e",
         f"SELECT wr_id FROM g5_write_metting WHERE wr_parent={parent_wr_id} AND wr_is_comment=1 ORDER BY wr_id"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if fetch.returncode != 0:
        print(f"댓글 ID 조회 실패: {fetch.stderr}", file=sys.stderr)
        return 3
    comment_ids = [int(x) for x in fetch.stdout.strip().split("\n") if x]
    print(f"그누보드5 댓글 {len(comment_ids)}건 발견")

    if len(comment_ids) != len(utterances):
        print(f"⚠️ 댓글 수({len(comment_ids)})와 발화 수({len(utterances)}) 불일치 — 매핑 부정확할 수 있음")

    # UPDATE SQL 생성 (UNICODE 한글 → SQL 에스케이프)
    updates = []
    for wr_id, utt in zip(comment_ids, utterances):
        author = f"회의_{utt['speaker']}".replace("'", "''")
        updates.append(f"UPDATE g5_write_metting SET wr_name='{author}' WHERE wr_id={wr_id};")

    # 임시 SQL 파일에 작성 후 실행 (긴 명령 회피)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
        sql_path = f.name
        f.write("\n".join(updates))

    try:
        result = subprocess.run(
            [mysql, "-u", "root", "metting", "--default-character-set=utf8mb4"],
            stdin=open(sql_path, encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode != 0:
            print(f"업데이트 실패: {result.stderr}", file=sys.stderr)
            return 4
    finally:
        Path(sql_path).unlink(missing_ok=True)

    print(f"✓ {len(updates)}건 업데이트 완료")
    return 0


def _update_via_python(parent_wr_id: int, utterances: list[dict]) -> int:
    """mysql.connector 사용 (현재 미구현, fallback로 _update_via_mysql_cli 호출)."""
    return _update_via_mysql_cli(parent_wr_id, utterances)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/update_comment_authors.py <meeting_id>")
        sys.exit(1)
    sys.exit(main(int(sys.argv[1])))
