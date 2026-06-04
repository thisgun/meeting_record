"""회의 음성 파일 자동 처리 데몬.

지정된 폴더(WATCH_DIR)를 감시하다가 오디오 파일이 들어오면
자동으로 main.py 파이프라인을 실행합니다.

사용:
    python watcher.py                  # WATCH_DIR 감시 시작
    python watcher.py --scan-now        # 폴더 한 번 스캔만 (기존 파일 처리 후 종료)
    python watcher.py --no-upload       # 로컬 DB 저장만

설정 (.env):
    WATCH_DIR=./data/watch              # 감시할 폴더
    WATCH_SPEAKERS=                     # 화자 수 (빈 값이면 자동 추정)
    WATCH_STABILITY_SEC=5               # 파일 크기가 N초간 변하지 않으면 "복사 완료"로 판단
    WATCH_NO_UPLOAD=0                   # 1이면 main.py --no-upload로 실행
    WATCH_PROCESSED_DIR=                # 처리 끝나면 옮길 폴더 (기본: ./data/uploads)
    WATCH_LOG=./data/watch.log          # 처리 이력 로그
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from meeting_record.console import configure_utf8_stdio


configure_utf8_stdio()
load_dotenv(override=True)

PROJECT_ROOT = Path(__file__).resolve().parent
WATCH_DIR = Path(os.getenv("WATCH_DIR", "./data/watch"))
if not WATCH_DIR.is_absolute():
    WATCH_DIR = PROJECT_ROOT / WATCH_DIR
WATCH_DIR.mkdir(parents=True, exist_ok=True)

WATCH_LOG = Path(os.getenv("WATCH_LOG", "./data/watch.log"))
if not WATCH_LOG.is_absolute():
    WATCH_LOG = PROJECT_ROOT / WATCH_LOG
WATCH_LOG.parent.mkdir(parents=True, exist_ok=True)

WATCH_SPEAKERS = os.getenv("WATCH_SPEAKERS", "").strip()
WATCH_STABILITY_SEC = float(os.getenv("WATCH_STABILITY_SEC", "5"))
WATCH_NO_UPLOAD = os.getenv("WATCH_NO_UPLOAD", "").lower().strip() in ("1", "true", "yes", "on")

SUPPORTED_EXT = {".mp3", ".m4a", ".wav", ".amr", ".aac", ".ogg", ".flac", ".wma"}


def log(msg: str) -> None:
    """콘솔과 파일에 동시 기록."""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with WATCH_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_stable(path: Path, stability_sec: float = WATCH_STABILITY_SEC) -> bool:
    """파일 크기가 stability_sec 초간 변하지 않으면 True.
    (복사가 끝났는지 확인)"""
    try:
        size1 = path.stat().st_size
    except FileNotFoundError:
        return False
    time.sleep(stability_sec)
    try:
        size2 = path.stat().st_size
    except FileNotFoundError:
        return False
    return size1 == size2 and size1 > 0


def process_file(audio_path: Path, *, no_upload: bool = WATCH_NO_UPLOAD) -> int:
    """main.py를 실행해서 회의록 처리."""
    log(f"▶ 처리 시작: {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)")

    cmd = [
        sys.executable, "-u", str(PROJECT_ROOT / "main.py"),
        str(audio_path),
    ]
    if WATCH_SPEAKERS:
        cmd += ["--speakers", WATCH_SPEAKERS]
    if no_upload:
        cmd.append("--no-upload")

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

    start = time.time()
    try:
        proc = subprocess.run(cmd, env=env, cwd=str(PROJECT_ROOT))
        elapsed = int(time.time() - start)
        if proc.returncode == 0:
            log(f"✓ 완료: {audio_path.name} ({elapsed // 60}분 {elapsed % 60}초)")
            return 0
        else:
            log(f"✗ 실패 (exit {proc.returncode}): {audio_path.name} ({elapsed // 60}분)")
            try:
                from src.notifier import notify_meeting_failed
                notify_meeting_failed(
                    source_file=str(audio_path),
                    error=f"main.py exit code {proc.returncode}",
                    stage="watcher → main.py",
                    elapsed_sec=elapsed,
                )
            except Exception:
                pass
            return proc.returncode
    except Exception as e:
        log(f"✗ 예외: {audio_path.name} - {e}")
        try:
            from src.notifier import notify_meeting_failed
            notify_meeting_failed(
                source_file=str(audio_path),
                error=str(e),
                stage="watcher 호출",
                elapsed_sec=int(time.time() - start),
            )
        except Exception:
            pass
        return 1


class AudioFileHandler(FileSystemEventHandler):
    def __init__(self, *, no_upload: bool = WATCH_NO_UPLOAD):
        super().__init__()
        self._processing: set[str] = set()
        self.no_upload = no_upload

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        self._handle(Path(event.dest_path))

    def _handle(self, path: Path):
        if path.suffix.lower() not in SUPPORTED_EXT:
            return
        key = str(path.resolve())
        if key in self._processing:
            return
        self._processing.add(key)
        try:
            log(f"📥 감지: {path.name}")
            log(f"  안정성 확인 중 ({WATCH_STABILITY_SEC}초)...")
            if not is_stable(path):
                log(f"  파일이 아직 변경 중이거나 사라짐. 스킵.")
                return
            process_file(path, no_upload=self.no_upload)
        finally:
            self._processing.discard(key)


def scan_existing(handler: AudioFileHandler) -> None:
    """시작 시 폴더에 이미 있는 파일들 처리."""
    files = [p for p in WATCH_DIR.iterdir()
             if p.is_file() and p.suffix.lower() in SUPPORTED_EXT]
    if files:
        log(f"기존 파일 {len(files)}개 발견. 순차 처리.")
        for p in files:
            handler._handle(p)


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="회의 음성 자동 처리 감시 데몬")
    parser.add_argument("--scan-now", action="store_true",
                        help="기존 파일만 처리하고 종료")
    parser.add_argument("--no-upload", action="store_true",
                        help="main.py --no-upload로 실행하여 로컬 DB에만 저장")
    args = parser.parse_args(argv)
    no_upload = args.no_upload or WATCH_NO_UPLOAD

    log("=" * 60)
    log(f"watcher 시작")
    log(f"감시 폴더: {WATCH_DIR}")
    log(f"감시 확장자: {', '.join(sorted(SUPPORTED_EXT))}")
    log(f"WATCH_SPEAKERS: {WATCH_SPEAKERS or '자동 추정'}")
    log(f"WATCH_STABILITY_SEC: {WATCH_STABILITY_SEC}")
    log(f"업로드: {'생략 (--no-upload)' if no_upload else '사용'}")
    log("=" * 60)

    handler = AudioFileHandler(no_upload=no_upload)
    scan_existing(handler)

    if args.scan_now:
        log("--scan-now 종료")
        return 0

    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()
    log(f"감시 중... Ctrl+C로 종료. 파일을 {WATCH_DIR} 에 떨어뜨리세요.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("종료 신호 수신")
        observer.stop()
    observer.join()
    log("watcher 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
