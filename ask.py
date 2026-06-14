"""회의록 RAG 질의응답 CLI.

사용:
    python ask.py "지난달 산업안전 회의에서 뭐 결정했어?"
    python ask.py --chat             # 대화형 모드 (이전 질문 맥락 유지, 후속 질문 가능)
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


# 멀티턴 맥락이 무한정 커지지 않도록 최근 N턴(=2N 메시지)만 유지
_MAX_HISTORY_TURNS = 6


def _print_hits(result: dict) -> None:
    print("=" * 60)
    for h in result["hits"]:
        print(f"--- [meeting {h['meeting_id']}] {h['kind']} score={h['score']:.3f}")
        print(h["text"][:300])
        print()
    print("=" * 60)


def run_chat(cfg, *, top_k: int | None, show_hits: bool) -> int:
    print("대화형 RAG 모드. 질문을 입력하세요. (종료: 빈 줄 또는 'exit')\n")
    # 첫 질문에서만 인덱스를 최신화하고, 이후 턴은 재인덱싱 생략
    indexed = False
    history: list[dict] = []
    while True:
        try:
            question = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in ("exit", "quit", "/q"):
            break

        result = answer_question(
            cfg, question, top_k=top_k, history=history, auto_index=not indexed
        )
        indexed = True
        if show_hits:
            _print_hits(result)
        print(f"\nbot> {result['answer_with_sources']}\n")

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": result["answer"]})
        if len(history) > _MAX_HISTORY_TURNS * 2:
            history = history[-_MAX_HISTORY_TURNS * 2:]
    print("대화 종료.")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="회의록 RAG 질의응답")
    parser.add_argument("question", nargs="?", help="질문")
    parser.add_argument("--chat", action="store_true", help="대화형 모드 (맥락 유지)")
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
        if not args.question and not args.chat:
            return 0

    if args.chat:
        return run_chat(cfg, top_k=args.top_k, show_hits=args.show_hits)

    if not args.question:
        parser.print_help()
        return 1

    print(f"질문: {args.question}")
    print("검색 및 답변 생성 중...\n")
    result = answer_question(cfg, args.question, top_k=args.top_k)

    if args.show_hits:
        _print_hits(result)

    print(result["answer_with_sources"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
