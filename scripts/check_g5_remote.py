"""원격 그누보드5 API 진단.

사용:
    python scripts/check_g5_remote.py                    # 모든 타겟 점검
    python scripts/check_g5_remote.py --target remote    # 특정 타겟만

각 타겟에 대해:
1. health.php 응답 확인
2. 게시판 존재 여부
3. 인증/쓰기 동작 (post/comment/update/list/delete 시도)
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from meeting_record.console import configure_utf8_stdio
from src.g5_client import build_clients_from_env


def main() -> int:
    configure_utf8_stdio()
    p = argparse.ArgumentParser()
    p.add_argument("--target", help="특정 타겟 이름만 점검 (예: remote)")
    args = p.parse_args()

    cfg = load_config()
    clients = build_clients_from_env(cfg)
    if not clients:
        print("[error] G5 클라이언트 없음 — .env 확인")
        return 1

    if args.target:
        clients = [c for c in clients if c.name == args.target.lower()]
        if not clients:
            print(f"타겟 '{args.target}' 없음")
            return 1

    fail = 0
    for c in clients:
        print(f"\n{'='*60}")
        print(f"타겟: {c.name}")
        print(f"URL:  {c.api_base}")
        print("=" * 60)

        # 1. health.php
        try:
            h = c.health()
            print(f"✓ health.php OK")
            print(f"  PHP: {h.get('php_version')}")
            print(f"  G5 경로: {h.get('g5_path')}")
            print(f"  G5 설치됨: {h.get('g5_installed')}")
            print(f"  DB 연결: {h.get('db_connected')}")
            print(f"  bo_table='{h.get('bo_table')}' 존재: {h.get('board_exists')}")
            if h.get("board_subject"):
                print(f"  게시판 제목: {h.get('board_subject')}")
            if not h.get("board_exists"):
                print(f"  ⚠️ 게시판이 없습니다. setup_board.php를 한 번 실행하세요.")
                fail += 1
                continue
        except Exception as e:
            print(f"✗ health.php 실패: {e}")
            fail += 1
            continue

        # 2. 인증 동작 확인 (post + comment + update + list + delete)
        print(f"\n시도: 테스트 게시글 1건 작성 후 자동 삭제")
        wr_id = None
        run_id = uuid.uuid4().hex[:12]
        try:
            post = c.create_post(
                subject=f"[연결 테스트] 자동 삭제 예정 ({run_id})",
                content=f"g5_meeting_api 연결 점검용. 곧 자동 삭제됩니다.\nrun_id={run_id}",
                idempotency_key=f"meeting_record:check_g5_remote:post:{c.name}:{run_id}",
            )
            wr_id = post["wr_id"]
            print(f"  ✓ 게시글 생성 OK: wr_id={wr_id}")
            print(f"  → 게시판 URL: {post.get('url')}")
            c.update_post(wr_id, subject="[연결 테스트] 수정 확인", content="게시글 수정 API 확인.")
            print(f"  ✓ 게시글 수정 OK")
            comment = c.create_comment(
                wr_id,
                f"댓글 생성 API 확인. run_id={run_id}",
                idempotency_key=f"meeting_record:check_g5_remote:comment:{c.name}:{run_id}",
            )
            comment_id = comment["comment_id"]
            print(f"  ✓ 댓글 생성 OK: comment_id={comment_id}")
            c.update_comment(comment_id, content="댓글 수정 API 확인.", author_name="회의_점검")
            print(f"  ✓ 댓글 수정 OK")
            comments = c.list_comments(wr_id)
            print(f"  ✓ 댓글 목록 OK: {len(comments)}건")
        except Exception as e:
            print(f"  ✗ 쓰기 API 실패: {e}")
            fail += 1
        finally:
            if wr_id:
                try:
                    c.delete_post(wr_id)
                    print(f"  ✓ 테스트 게시글 삭제 OK")
                except Exception as e:
                    print(f"  ⚠️ 테스트 게시글 자동 삭제 실패: wr_id={wr_id}, run_id={run_id}, {e}")
                    print("     게시판에서 위 wr_id의 '[연결 테스트]' 글을 수동 삭제하세요.")
                    fail += 1

    print(f"\n{'='*60}")
    if fail == 0:
        print(f"✓ 모든 타겟 정상")
    else:
        print(f"⚠️ {fail}개 타겟 문제 발생")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
