r"""SQLite + MariaDB(meeting DB) 백업.

사용:
    python scripts/backup.py                            # ./data/backups/<날짜>/ 로 백업
    python scripts/backup.py --out D:\backup            # 출력 폴더 지정
    python scripts/backup.py --keep 14                  # 14일 초과 백업 자동 삭제
    python scripts/backup.py --no-mysql                 # SQLite만
    python scripts/backup.py --no-sqlite                # MariaDB만

Windows 작업 스케줄러 등록 예시:
    cd meeting_record
    $project = (Resolve-Path .).Path
    schtasks /create /tn "MeetingRecordBackup" /sc DAILY /st 03:00 `
        /tr "cmd /c `"cd /d $project && python scripts\backup.py --keep 30`""
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XAMPP_MYSQLDUMP = r"C:\xampp\mysql\bin\mysqldump.exe"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _find_mysqldump(explicit: str = "") -> str | None:
    candidates = [
        explicit,
        _env("MYSQLDUMP_PATH"),
        _env("MYSQL_DUMP_PATH"),
        shutil.which("mysqldump") or "",
        DEFAULT_XAMPP_MYSQLDUMP,
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


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
        print(f"[ok] SQLite: {out.name} ({size_mb:.2f} MB)")
        return out
    except Exception as e:
        print(f"[error] SQLite 백업 실패: {e}")
        return None


def backup_mariadb(
    out_dir: Path,
    *,
    dump_path: str = "",
    db_name: str = "meeting",
    user: str = "root",
    password: str = "",
    host: str = "127.0.0.1",
    port: str = "3306",
) -> Path | None:
    """MariaDB meeting DB 덤프 (mysqldump)."""
    mysqldump = _find_mysqldump(dump_path)
    if not mysqldump:
        print("[skip] mysqldump 없음: MYSQLDUMP_PATH 설정 또는 PATH 등록 필요")
        return None
    out = out_dir / f"{db_name}.sql"
    cmd = [
        mysqldump,
        "-h", host,
        "-P", str(port),
        "-u", user,
        db_name,
        "--default-character-set=utf8mb4",
        "--routines", "--events", "--triggers",
        "--single-transaction",
        "--result-file=" + str(out),
    ]
    env = os.environ.copy()
    if password:
        env["MYSQL_PWD"] = password
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
        if r.returncode != 0:
            print(f"[error] mysqldump 실패: {r.stderr[:300]}")
            return None
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"[ok] MariaDB: {out.name} ({size_mb:.2f} MB)")
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
    parser.add_argument("--mysql-dump-path", default=_env("MYSQLDUMP_PATH") or _env("MYSQL_DUMP_PATH"), help="mysqldump 실행 파일 경로")
    parser.add_argument("--mysql-db", default=_env("MYSQL_DATABASE", "meeting"), help="MariaDB DB명 (기본 meeting)")
    parser.add_argument("--mysql-user", default=_env("MYSQL_USER", "root"), help="MariaDB 사용자 (기본 root)")
    parser.add_argument("--mysql-password", default=_env("MYSQL_PASSWORD"), help="MariaDB 비밀번호")
    parser.add_argument("--mysql-host", default=_env("MYSQL_HOST", "127.0.0.1"), help="MariaDB 호스트")
    parser.add_argument("--mysql-port", default=_env("MYSQL_PORT", "3306"), help="MariaDB 포트")
    args = parser.parse_args(argv)

    cfg = load_config()
    base = Path(args.out) if args.out else PROJECT_ROOT / "data" / "backups"
    base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = base / ts
    target.mkdir()
    print(f"백업 대상 폴더: {target}\n")

    results = []
    if not args.no_sqlite:
        results.append(backup_sqlite(Path(cfg.db_path), target))
    if not args.no_mysql:
        results.append(backup_mariadb(
            target,
            dump_path=args.mysql_dump_path,
            db_name=args.mysql_db,
            user=args.mysql_user,
            password=args.mysql_password,
            host=args.mysql_host,
            port=args.mysql_port,
        ))

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
