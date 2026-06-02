r"""SQLite + MariaDB(metting DB) 백업.

사용:
    python scripts/backup.py                            # ./data/backups/<날짜>/ 로 백업
    python scripts/backup.py --out D:\backup            # 출력 폴더 지정
    python scripts/backup.py --keep 14                  # 14일 초과 백업 자동 삭제
    python scripts/backup.py --no-mysql                 # SQLite만
    python scripts/backup.py --no-sqlite                # MariaDB만

Windows 작업 스케줄러 등록 예시:
    schtasks /create /tn "MettingBackup" /sc DAILY /st 03:00 \
        /tr "python c:\dev2\metting_record\scripts\backup.py --keep 30"
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config


MYSQL_DUMP = r"C:\xampp\mysql\bin\mysqldump.exe"


def backup_sqlite(db_path: Path, out_dir: Path) -> Path | None:
    """SQLite 백업 (단순 파일 복사 + .bak 확장자).

    sqlite3.backup() API가 더 안전하지만 .db 직접 복사도 보통 충분.
    WAL 모드면 -wal 파일도 같이 백업.
    """
    if not db_path.exists():
        print(f"[skip] SQLite 파일 없음: {db_path}")
        return None
    out = out_dir / db_path.name
    # 안전한 백업: sqlite3 backup API 사용
    import sqlite3
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(out))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"✓ SQLite: {out.name} ({size_mb:.2f} MB)")
        return out
    except Exception as e:
        print(f"[error] SQLite 백업 실패: {e}")
        return None


def backup_mariadb(out_dir: Path, db_name: str = "metting") -> Path | None:
    """MariaDB metting DB 덤프 (mysqldump)."""
    if not Path(MYSQL_DUMP).exists():
        print(f"[skip] mysqldump 없음: {MYSQL_DUMP}")
        return None
    out = out_dir / f"{db_name}.sql"
    cmd = [
        MYSQL_DUMP, "-u", "root", db_name,
        "--default-character-set=utf8mb4",
        "--routines", "--events", "--triggers",
        "--single-transaction",
        "--result-file=" + str(out),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print(f"[error] mysqldump 실패: {r.stderr[:300]}")
            return None
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"✓ MariaDB: {out.name} ({size_mb:.2f} MB)")
        return out
    except Exception as e:
        print(f"[error] MariaDB 백업 실패: {e}")
        return None


def cleanup_old(base_dir: Path, keep_days: int) -> int:
    """keep_days 초과 백업 폴더 삭제."""
    if not base_dir.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=keep_days)
    deleted = 0
    for sub in base_dir.iterdir():
        if not sub.is_dir():
            continue
        try:
            # 폴더명이 YYYY-MM-DD 또는 YYYY-MM-DD_HHMMSS 형식 가정
            name = sub.name.split("_")[0]
            ts = datetime.strptime(name, "%Y-%m-%d")
        except ValueError:
            continue
        if ts < cutoff:
            shutil.rmtree(sub, ignore_errors=True)
            print(f"  - 삭제: {sub.name}")
            deleted += 1
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="회의록 데이터 백업")
    parser.add_argument("--out", help="백업 루트 폴더 (기본 ./data/backups)")
    parser.add_argument("--keep", type=int, default=30, help="N일 초과 백업 삭제 (기본 30, 0이면 삭제 안 함)")
    parser.add_argument("--no-mysql", action="store_true")
    parser.add_argument("--no-sqlite", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config()
    base = Path(args.out) if args.out else Path("./data/backups").resolve()
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = base / ts
    target.mkdir()
    print(f"백업 대상 폴더: {target}\n")

    results = []
    if not args.no_sqlite:
        results.append(backup_sqlite(Path(cfg.db_path), target))
    if not args.no_mysql:
        results.append(backup_mariadb(target))

    success = sum(1 for r in results if r is not None)
    print(f"\n완료: {success}개 항목 백업")

    if args.keep > 0:
        print(f"\n{args.keep}일 초과 백업 정리 중...")
        n = cleanup_old(base, args.keep)
        if n:
            print(f"  {n}개 폴더 삭제")
        else:
            print("  삭제 대상 없음")

    return 0 if success > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
