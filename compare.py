"""회의 비교 CLI.

사용:
    python compare.py 3 5                            # meeting_id 3과 5 직접 비교
    python compare.py --timeline                     # 월별 회의 통계
    python compare.py --timeline --since 2026-01-01
    python compare.py --keyword-trend "산업재해"      # 키워드 월별 등장 빈도
    python compare.py --speaker-trend 사용자3         # 특정 화자 월별 발언 추이
    python compare.py --top-keywords 5               # meeting_id=5의 상위 키워드
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from src import comparator, stats, storage


def _ts(sec): return stats.format_duration(sec)


def cmd_compare_two(args, cfg) -> int:
    a, b = args.id_a, args.id_b
    print(f"\n=== 회의 #{a} ⟷ #{b} 비교 ===\n")
    try:
        result = comparator.compare_two(cfg.db_path, a, b)
    except ValueError as e:
        print(f"실패: {e}", file=sys.stderr)
        return 1

    ma, mb = result["meetings"]["a"], result["meetings"]["b"]
    print(f"[A] #{a} {ma['title']}")
    print(f"      {ma['created_at'][:10]} · {_ts(ma['duration_sec'])} · 발화 {result['meta_diff']['utterance_count_a']} · 화자 {ma['speaker_count']}")
    print(f"[B] #{b} {mb['title']}")
    print(f"      {mb['created_at'][:10]} · {_ts(mb['duration_sec'])} · 발화 {result['meta_diff']['utterance_count_b']} · 화자 {mb['speaker_count']}")
    print()

    # 메타 차이
    md = result["meta_diff"]
    print("─ 메타 차이 ─")
    print(f"  길이:   A {_ts(md['duration_sec_a'])} vs B {_ts(md['duration_sec_b'])} (차 {_ts(abs(md['duration_sec_a']-md['duration_sec_b']))})")
    print(f"  발화:   A {md['utterance_count_a']}건 vs B {md['utterance_count_b']}건")
    print(f"  화자:   A {md['speaker_count_a']}명 vs B {md['speaker_count_b']}명")
    print()

    # 화자
    sp = result["speakers"]
    print("─ 화자 ─")
    print(f"  공통:        {', '.join(sp['common']) or '(없음)'}")
    print(f"  A에만:       {', '.join(sp['only_in_a']) or '(없음)'}")
    print(f"  B에만:       {', '.join(sp['only_in_b']) or '(없음)'}")
    print()

    # 키워드
    kw = result["keywords"]
    print(f"─ 공통 핵심어 (상위 {len(kw['shared'])}) ─")
    for w, na, nb in kw["shared"][:15]:
        print(f"  {w:<12} A:{na:>3}  B:{nb:>3}")
    print(f"\n─ A에만 자주 등장 ─")
    for w, n in kw["only_a"][:10]:
        print(f"  {w:<12} {n:>3}회")
    print(f"\n─ B에만 자주 등장 ─")
    for w, n in kw["only_b"][:10]:
        print(f"  {w:<12} {n:>3}회")

    return 0


def cmd_timeline(args, cfg) -> int:
    rows = comparator.timeline_stats(cfg.db_path, since=args.since, until=args.until)
    if not rows:
        print("기간 내 회의 없음")
        return 0
    print(f"\n=== 월별 회의 통계 ===\n")
    print(f"{'월':<10} {'회의수':>6} {'총 길이':>12} {'평균':>10} {'총 발화':>8}")
    print("-" * 55)
    for r in rows:
        print(f"{r['month']:<10} {r['count']:>6} {_ts(r['total_sec']):>12} {_ts(r['avg_sec']):>10} {r['utterance_count']:>8}")
    return 0


def cmd_keyword_trend(args, cfg) -> int:
    rows = comparator.keyword_trend(cfg.db_path, args.keyword, since=args.since, until=args.until)
    if not rows:
        print(f"'{args.keyword}' 등장한 회의 없음")
        return 0
    print(f"\n=== '{args.keyword}' 월별 등장 빈도 ===\n")
    print(f"{'월':<10} {'회의수':>6} {'등장 횟수':>10}")
    print("-" * 30)
    for r in rows:
        print(f"{r['month']:<10} {r['meeting_count']:>6} {r['occurrence_count']:>10}")
    return 0


def cmd_speaker_trend(args, cfg) -> int:
    rows = comparator.speaker_trend(cfg.db_path, args.speaker, since=args.since, until=args.until)
    if not rows:
        print(f"화자 '{args.speaker}' 발언 없음")
        return 0
    print(f"\n=== '{args.speaker}' 월별 발언 통계 ===\n")
    print(f"{'월':<10} {'회의수':>6} {'발화수':>6} {'발언 시간':>12}")
    print("-" * 40)
    for r in rows:
        print(f"{r['month']:<10} {r['meeting_count']:>6} {r['utterance_count']:>6} {_ts(r['total_sec']):>12}")
    return 0


def cmd_top_keywords(args, cfg) -> int:
    data = storage.get_meeting(cfg.db_path, args.meeting_id)
    if not data:
        print(f"meeting_id={args.meeting_id} 없음", file=sys.stderr)
        return 1
    texts = [u["text"] for u in data["utterances"]]
    kws = comparator.top_keywords(texts, top_n=args.top)
    print(f"\n=== 회의 #{args.meeting_id} 상위 키워드 ({len(kws)}개) ===\n")
    for w, n in kws:
        print(f"  {w:<14} {n:>4}회")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="회의 비교 분석", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("id_a", nargs="?", type=int, help="비교 대상 A의 meeting_id")
    p.add_argument("id_b", nargs="?", type=int, help="비교 대상 B의 meeting_id")
    p.add_argument("--timeline", action="store_true", help="월별 회의 통계")
    p.add_argument("--keyword-trend", help="키워드 월별 등장 빈도")
    p.add_argument("--speaker-trend", help="특정 화자 월별 발언 추이")
    p.add_argument("--top-keywords", type=int, metavar="MEETING_ID", help="특정 회의 상위 키워드")
    p.add_argument("--top", type=int, default=30, help="상위 N개 (기본 30)")
    p.add_argument("--since")
    p.add_argument("--until")

    args = p.parse_args(argv)
    cfg = load_config()
    storage.init_db(cfg.db_path)

    if args.timeline:
        return cmd_timeline(args, cfg)
    if args.keyword_trend:
        args.keyword = args.keyword_trend
        return cmd_keyword_trend(args, cfg)
    if args.speaker_trend:
        args.speaker = args.speaker_trend
        return cmd_speaker_trend(args, cfg)
    if args.top_keywords is not None:
        args.meeting_id = args.top_keywords
        return cmd_top_keywords(args, cfg)
    if args.id_a and args.id_b:
        return cmd_compare_two(args, cfg)

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
