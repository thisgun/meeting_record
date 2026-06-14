"""그누보드5 게시판 시맨틱 검색 인덱서 CLI.

게시판 글을 임베딩해 posts.db에 저장한다. semantic_search.php가 이 DB를 읽어 검색한다.

사용:
    python semantic_index.py                 # .env의 SEMANTIC_BOARDS 인덱싱
    python semantic_index.py free notice     # 지정 게시판만 인덱싱
    python semantic_index.py --search "환불 규정"   # (디버그) 파이썬에서 검색 테스트
"""
from __future__ import annotations

import argparse
import sys

from config import load_config
from src.g5_client import G5MeetingApiClient
from src.post_index import index_boards, search_posts


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="그누보드5 게시판 시맨틱 검색 인덱서")
    parser.add_argument("boards", nargs="*", help="인덱싱할 bo_table (생략 시 SEMANTIC_BOARDS)")
    parser.add_argument("--search", metavar="QUERY", help="(디버그) 인덱스에서 검색 테스트")
    parser.add_argument("--rebuild", action="store_true", help="증분 무시하고 전체 재임베딩")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)

    cfg = load_config()

    if args.search:
        hits = search_posts(
            cfg.semantic_db_path, args.search,
            embed_model=cfg.embed_model, host=cfg.ollama_host,
            top_k=args.top_k, min_score=cfg.rag_min_score,
        )
        print(f"검색: {args.search}  (DB: {cfg.semantic_db_path})\n")
        for h in hits:
            print(f"  {h['score']:.3f}  [{h['bo_table']}#{h['wr_id']}] {h['subject']}")
            print(f"          {h['snippet'][:80]}")
        if not hits:
            print("  (결과 없음 — 먼저 인덱싱했는지 확인하세요)")
        return 0

    boards = args.boards or list(cfg.semantic_boards)
    if not boards:
        print("인덱싱할 게시판이 없습니다. SEMANTIC_BOARDS를 설정하거나 인자로 지정하세요.", file=sys.stderr)
        return 1

    client = G5MeetingApiClient(
        api_base=cfg.g5_api_base, api_token=cfg.g5_api_token, name="semantic",
    )
    mode = " (전체 재구축)" if args.rebuild else " (증분)"
    print(f"인덱싱 대상: {', '.join(boards)}{mode}  →  {cfg.semantic_db_path}")
    result = index_boards(
        client, boards, db_path=cfg.semantic_db_path,
        embed_model=cfg.embed_model, host=cfg.ollama_host, force=args.rebuild,
    )
    total = sum(n for n in result.values() if n > 0)
    print(f"완료: 글 {total}개 인덱싱 ({cfg.semantic_db_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
