"""wr_id=721의 잘린 JSON 응답을 보정하고 본문/제목을 업데이트.

SQLite의 raw response에서 title과 summary_md를 추출,
잘림 부분 보정 후 SQLite + 그누보드5 모두 업데이트.
"""
from __future__ import annotations

import json
import re
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from src import storage


def extract_partial_json(raw: str) -> dict:
    """잘린 JSON에서 title과 summary_md를 추출."""
    # "원본 응답:" 이후 부분만 사용
    if "원본 응답:" in raw:
        raw = raw.split("원본 응답:", 1)[1].strip()

    # title 추출
    m = re.search(r'"title"\s*:\s*"([^"]+)"', raw)
    title = m.group(1) if m else "회의록"

    # summary_md 추출 (열린 따옴표부터 마지막 비어있지 않은 문자까지)
    m = re.search(r'"summary_md"\s*:\s*"(.*)', raw, re.DOTALL)
    if not m:
        raise ValueError("summary_md 키를 못 찾았습니다")
    md = m.group(1)

    # 끝의 trailing 따옴표/공백/} 제거
    md = md.rstrip()
    # JSON escape 풀기: \n → 줄바꿈, \" → ", \\ → \
    md = md.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    # 마지막 닫는 따옴표 한 개가 잘려나간 경우 그대로 OK; 있다면 제거
    if md.endswith('"'):
        md = md[:-1]
    return {"title": title.strip(), "summary_md": md.strip()}


def main(meeting_id: int) -> int:
    cfg = load_config()
    meeting = storage.get_meeting(cfg.db_path, meeting_id)
    if not meeting:
        print(f"meeting_id={meeting_id} 없음")
        return 1

    raw = meeting["meeting"]["summary_md"]
    print(f"raw 길이: {len(raw)}자")

    fixed = extract_partial_json(raw)
    print(f"추출된 title: {fixed['title']}")
    print(f"추출된 summary_md 길이: {len(fixed['summary_md'])}자")
    print()
    print("=== 보정된 summary_md 앞 600자 ===")
    print(fixed["summary_md"][:600])
    print()
    print("=== 보정된 summary_md 마지막 300자 ===")
    print(fixed["summary_md"][-300:])

    # SQLite 업데이트
    import sqlite3
    with sqlite3.connect(str(cfg.db_path)) as conn:
        conn.execute(
            "UPDATE meetings SET title=?, summary_md=? WHERE id=?",
            (fixed["title"], fixed["summary_md"], meeting_id),
        )
    print(f"\n✓ SQLite meeting_id={meeting_id} 업데이트 완료")

    # 그누보드5도 업데이트
    remote_post_id = meeting["meeting"]["remote_post_id"]
    if remote_post_id:
        wr_id = int(remote_post_id)
        mysql = r"C:\xampp\mysql\bin\mysql.exe"
        # 임시 파일로 SQL (긴 본문 안전하게)
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
            sql_path = f.name
            esc_title = fixed["title"].replace("\\", "\\\\").replace("'", "''")
            esc_content = fixed["summary_md"].replace("\\", "\\\\").replace("'", "''")
            f.write(f"UPDATE g5_write_metting SET wr_subject='{esc_title}', wr_content='{esc_content}' WHERE wr_id={wr_id};")
        result = subprocess.run(
            [mysql, "-u", "root", "metting", "--default-character-set=utf8mb4"],
            stdin=open(sql_path, encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8",
        )
        Path(sql_path).unlink(missing_ok=True)
        if result.returncode != 0:
            print(f"그누보드5 업데이트 실패: {result.stderr}")
            return 2
        print(f"✓ 그누보드5 wr_id={wr_id} 업데이트 완료")

    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 6))
