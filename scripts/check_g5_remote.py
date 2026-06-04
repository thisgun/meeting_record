"""원격 그누보드5 API 진단.

사용:
    python scripts/check_g5_remote.py                    # 모든 타겟 점검
    python scripts/check_g5_remote.py --target remote    # 특정 타겟만

각 타겟에 대해:
1. health.php 응답 확인
2. 게시판 존재 여부
3. 인증 동작 (post 시도, 즉시 삭제)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from src.g5_client import build_clients_from_env


def main() -> int:
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

        # 2. 인증 동작 확인 (post + comment, 즉시 삭제는 사용자 수동)
        print(f"\n시도: 테스트 게시글 1건 작성 (확인 후 수동 삭제 권장)")
        try:
            post = c.create_post(
                subject="[연결 테스트] 삭제해 주세요",
                content="g5_meeting_api 연결 점검용. 확인 후 삭제하세요.",
            )
            wr_id = post["wr_id"]
            print(f"  ✓ 게시글 생성 OK: wr_id={wr_id}")
            print(f"  → 게시판 URL: {post.get('url')}")
        except Exception as e:
            print(f"  ✗ 게시글 생성 실패: {e}")
            fail += 1

    print(f"\n{'='*60}")
    if fail == 0:
        print(f"✓ 모든 타겟 정상")
    else:
        print(f"⚠️ {fail}개 타겟 문제 발생")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
