"""회의록 RAG 질의응답 CLI.

사용:
    python ask.py "지난달 산업안전 회의에서 뭐 결정했어?"
    python ask.py --index            # 인덱싱만 수행
    python ask.py --rebuild          # 전체 재인덱싱
    python ask.py "질문" --top-k 10  # 검색 청크 수 조정
    python ask.py "질문" --show-hits # 검색된 청크 원문도 출력 (디버그)
"""
from __future__ import annotations

import argparse
import sys

from config import load_config
from src.embeddings import index_all
from src.rag import answer_question


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="회의록 RAG 질의응답")
    parser.add_argument("question", nargs="?", help="질문")
    parser.add_argument("--index", action="store_true", help="인덱싱만 수행하고 종료")
    parser.add_argument("--rebuild", action="store_true", help="전체 재인덱싱 후 종료")
    parser.add_argument("--top-k", type=int, default=None, help="검색할 청크 수")
    parser.add_argument("--show-hits", action="store_true", help="검색된 청크 출력 (디버그)")
    args = parser.parse_args(argv)

    cfg = load_config()

    if args.index or args.rebuild:
        print(f"인덱싱 시작 (모델: {cfg.embed_model}{', 전체 재구축' if args.rebuild else ''})")
        n = index_all(cfg.db_path, embed_model=cfg.embed_model, host=cfg.ollama_host,
                      force=args.rebuild)
        print(f"완료: 회의 {n}건 인덱싱")
        if not args.question:
            return 0

    if not args.question:
        parser.print_help()
        return 1

    print(f"질문: {args.question}")
    print("검색 및 답변 생성 중...\n")
    result = answer_question(cfg, args.question, top_k=args.top_k)

    if args.show_hits:
        print("=" * 60)
        for h in result["hits"]:
            print(f"--- [meeting {h['meeting_id']}] {h['kind']} score={h['score']:.3f}")
            print(h["text"][:300])
            print()
        print("=" * 60)

    print(result["answer_with_sources"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
