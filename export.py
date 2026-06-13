"""회의록 export CLI.

사용:
    python export.py 5                              # meeting_id=5 → ./data/exports/<title>.docx
    python export.py 5 --format html                # HTML로
    python export.py 5 --format all                 # docx + html 둘 다
    python export.py 5 --no-transcript              # 발화 전문 제외 (요약만)
    python export.py 5 --out my_report.docx         # 출력 경로 지정
    python export.py --all                          # 모든 회의 일괄 export

HTML로 출력 후 브라우저에서 Ctrl+P → "PDF로 저장"이 가장 깨끗한 PDF 생성 방법입니다.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from meeting_record.console import configure_utf8_stdio
from src import storage, exporter


def _safe_filename(name: str, max_len: int = 80) -> str:
    """파일명으로 쓸 수 있게 정리."""
    s = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:max_len] or "회의록"


def export_one(meeting_id: int, fmt: str, out: str | None, include_transcript: bool, cfg) -> list[Path]:
    data = storage.get_meeting(cfg.db_path, meeting_id)
    if not data:
        print(f"meeting_id={meeting_id} 없음", file=sys.stderr)
        return []
    meeting = data["meeting"]
    utterances = data["utterances"]

    default_dir = Path("./data/exports").resolve()
    default_dir.mkdir(parents=True, exist_ok=True)
    basename = _safe_filename(f"{meeting_id:03d}_{meeting.get('title','회의록')}")

    paths: list[Path] = []
    formats = ["docx", "html"] if fmt == "all" else [fmt]

    for f in formats:
        if out and len(formats) == 1:
            target = Path(out)
        else:
            target = default_dir / f"{basename}.{f}"
        if f == "docx":
            p = exporter.to_docx(meeting, utterances, target, include_transcript=include_transcript)
        elif f == "html":
            p = exporter.to_html(meeting, utterances, target, include_transcript=include_transcript)
        else:
            print(f"지원하지 않는 포맷: {f}", file=sys.stderr)
            continue
        paths.append(p)
        size_kb = p.stat().st_size / 1024
        print(f"✓ {f.upper()}: {p}  ({size_kb:.1f} KB)")
    return paths


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="회의록 export", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("meeting_id", nargs="?", type=int, help="export할 meeting_id")
    parser.add_argument("--all", action="store_true", help="모든 회의 일괄 export")
    parser.add_argument("--format", default="docx", choices=["docx", "html", "all"], help="출력 포맷 (기본 docx)")
    parser.add_argument("--out", help="출력 파일 경로 (단일 회의 + 단일 포맷일 때만)")
    parser.add_argument("--no-transcript", action="store_true", help="발화 전문 제외 (요약만)")

    args = parser.parse_args(argv)
    cfg = load_config()
    storage.init_db(cfg.db_path)

    if args.all:
        # 모든 회의 ID 가져오기
        import sqlite3
        with sqlite3.connect(str(cfg.db_path)) as conn:
            rows = conn.execute("SELECT id FROM meetings ORDER BY id").fetchall()
        ids = [r[0] for r in rows]
        print(f"총 {len(ids)}개 회의 export 시작\n")
        for mid in ids:
            print(f"--- meeting_id={mid} ---")
            export_one(mid, args.format, None, not args.no_transcript, cfg)
        return 0

    if args.meeting_id is None:
        parser.print_help()
        return 1

    paths = export_one(args.meeting_id, args.format, args.out, not args.no_transcript, cfg)
    return 0 if paths else 1


if __name__ == "__main__":
    sys.exit(main())
