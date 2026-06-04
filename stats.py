"""회의 통계 CLI.

사용:
    python stats.py 5                    # meeting_id=5 화자별 통계
    python stats.py 5 --time              # 시간 구간별 분포 추가
    python stats.py 5 --json              # JSON 출력 (다른 도구 연동용)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from meeting_record.console import configure_utf8_stdio
from src import stats as st
from src import storage


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    p = argparse.ArgumentParser(description="회의 통계")
    p.add_argument("meeting_id", type=int)
    p.add_argument("--time", action="store_true", help="시간 구간별 분포 표시")
    p.add_argument("--chunk", type=float, default=600.0, help="시간 구간 길이(초), 기본 600=10분")
    p.add_argument("--json", action="store_true", help="JSON 출력")

    args = p.parse_args(argv)
    cfg = load_config()
    data = storage.get_meeting(cfg.db_path, args.meeting_id)
    if not data:
        print(f"meeting_id={args.meeting_id} 없음", file=sys.stderr)
        return 1

    utts = [{
        "speaker": u["speaker"],
        "start": u["start_sec"],
        "end": u["end_sec"],
        "text": u["text"],
    } for u in data["utterances"]]

    speaker_stats = st.per_speaker_stats(utts)
    time_stats = st.time_distribution(utts, chunk_sec=args.chunk) if args.time else None

    if args.json:
        out = {"speakers": speaker_stats}
        if time_stats:
            out["timeline"] = time_stats
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"\n=== 회의 #{args.meeting_id}: {data['meeting']['title']} ===")
    print(f"총 발화 {len(utts)}건, 길이 {st.format_duration(data['meeting']['duration_sec'])}")
    print(st.format_speaker_table(speaker_stats))

    if time_stats:
        print(f"\n시간 구간별 ({args.chunk/60:.0f}분 단위)")
        print(f"{'구간':<20} {'발화':>5} {'발언 시간':>12} {'주도 화자':>20}")
        print("-" * 70)
        for t in time_stats:
            cs = st.format_duration(t["chunk_start"])
            ce = st.format_duration(t["chunk_end"])
            window = f"{cs}~{ce}"
            print(f"{window:<20} {t['count']:>5} {st.format_duration(t['total_sec']):>12} "
                  f"{t['top_speaker']}({t['top_speaker_count']}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
