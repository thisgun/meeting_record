"""회의록 검색 CLI.

사용:
    python search.py "산재 은폐"                    # 회의 + 발화 모두 검색
    python search.py "안전 점검" --speaker 사용자3   # 특정 화자 발화만
    python search.py "AI 도입" --meetings-only      # 회의 요약만
    python search.py "지게차" --utterances-only     # 발화만
    python search.py "산재" --since 2026-01-01 --until 2026-12-31
    python search.py --rebuild                      # FTS 인덱스 재구축

FTS5 쿼리 문법:
    "단어 OR 단어"      # OR
    "단어 단어"         # AND (기본)
    "구문 검색"         # 따옴표로 정확 일치
    "단어 NEAR/5 단어"  # 5단어 이내
    "산*"               # 접두사 매칭
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from meeting_record.console import configure_utf8_stdio
from src import storage


def _ts(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def cmd_search(args) -> int:
    cfg = load_config()
    storage.init_db(cfg.db_path)

    if not args.utterances_only:
        print(f"\n=== 회의 검색 결과 (상위 {args.limit}개) ===\n")
        try:
            meetings = storage.search_meetings(
                cfg.db_path, args.query,
                limit=args.limit, since=args.since, until=args.until,
                advanced=args.advanced,
            )
        except Exception as e:
            print(f"회의 검색 실패: {e}", file=sys.stderr)
            return 2
        if not meetings:
            print("  (검색 결과 없음)")
        for m in meetings:
            print(f"[#{m['id']}] {m['title']}")
            print(f"    📅 {m['created_at']}")
            print(f"    📄 {m['snippet']}")
            print()

    if not args.meetings_only:
        print(f"\n=== 발화 검색 결과 (상위 {args.limit}개) ===\n")
        try:
            utts = storage.search_utterances(
                cfg.db_path, args.query,
                speaker=args.speaker, meeting_id=args.meeting,
                limit=args.limit,
                advanced=args.advanced,
            )
        except Exception as e:
            print(f"발화 검색 실패: {e}", file=sys.stderr)
            return 2
        if not utts:
            print("  (검색 결과 없음)")
        for u in utts:
            print(f"[meeting#{u['meeting_id']} | {_ts(u['start_sec'])}] {u['speaker']}")
            print(f"    📝 {u['snippet']}")
            print(f"    📂 {u['meeting_title']}")
            print()

    return 0


def cmd_rebuild(args) -> int:
    cfg = load_config()
    print("FTS 인덱스 재구축 중...")
    storage.init_db(cfg.db_path)  # 스키마 보장
    storage.rebuild_fts(cfg.db_path)
    print("✓ 완료")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="회의록 검색 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("query", nargs="?", help="검색어")
    parser.add_argument("--limit", type=int, default=10, help="결과 개수 (기본 10)")
    parser.add_argument("--speaker", help="발화 화자 필터 (예: 사용자3, 회의_사용자3)")
    parser.add_argument("--meeting", type=int, help="특정 meeting_id만 검색")
    parser.add_argument("--since", help="이 날짜 이후 (ISO, 예: 2026-01-01)")
    parser.add_argument("--until", help="이 날짜 이전")
    parser.add_argument("--meetings-only", action="store_true", help="회의 요약만 검색")
    parser.add_argument("--utterances-only", action="store_true", help="발화만 검색")
    parser.add_argument("--rebuild", action="store_true", help="FTS 인덱스 재구축")
    parser.add_argument("--advanced", action="store_true", help="FTS5 MATCH 문법을 그대로 사용")

    args = parser.parse_args(argv)

    if args.rebuild:
        return cmd_rebuild(args)
    if not args.query:
        parser.print_help()
        return 1
    return cmd_search(args)


if __name__ == "__main__":
    sys.exit(main())
