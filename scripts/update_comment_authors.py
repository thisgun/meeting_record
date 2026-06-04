"""기존 그누보드5 댓글의 작성자명을 화자별로 일괄 업데이트.

사용:
    python scripts/update_comment_authors.py <meeting_id>

meeting_id의 발화 정보(SQLite)와 remote_post_id(그누보드5 wr_id)를 매핑해서
그누보드5 댓글들의 wr_name을 "회의_사용자N"으로 변경한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from src import storage
from src.g5_client import G5ApiError, build_clients_from_env


def _comment_id_for(index: int, utterance: dict, comments: list[dict]) -> int | None:
    if utterance.get("remote_comment_id"):
        return int(utterance["remote_comment_id"])
    if index < len(comments) and comments[index].get("comment_id"):
        return int(comments[index]["comment_id"])
    return None


def main(meeting_id: int) -> int:
    cfg = load_config()
    meeting = storage.get_meeting(cfg.db_path, meeting_id)
    if not meeting:
        print(f"meeting_id={meeting_id} 없음", file=sys.stderr)
        return 1

    parent_wr_id = meeting["meeting"]["remote_post_id"]
    if not parent_wr_id:
        print(f"meeting_id={meeting_id}는 그누보드5에 업로드 안 됨", file=sys.stderr)
        return 2
    parent_wr_id = int(parent_wr_id)
    utterances = meeting["utterances"]
    print(f"meeting_id={meeting_id}, parent wr_id={parent_wr_id}, 발화 {len(utterances)}건")

    clients = build_clients_from_env(cfg)
    if not clients:
        print("G5 클라이언트 없음 — .env 확인", file=sys.stderr)
        return 3
    client = clients[0]
    print(f"갱신 대상: [{client.name}] {client.api_base}")

    try:
        comments = []
        if any(not u.get("remote_comment_id") for u in utterances):
            comments = client.list_comments(parent_wr_id)
            print(f"그누보드5 댓글 {len(comments)}건 발견")
            if len(comments) != len(utterances):
                print(
                    f"⚠️ 댓글 수({len(comments)})와 발화 수({len(utterances)}) 불일치 — 순서 매핑이 부정확할 수 있음",
                    file=sys.stderr,
                )

        updated = 0
        skipped = 0
        for idx, utt in enumerate(utterances):
            comment_id = _comment_id_for(idx, utt, comments)
            if not comment_id:
                skipped += 1
                print(f"[warn] 발화 id={utt['id']}의 원격 댓글 ID를 찾지 못해 스킵", file=sys.stderr)
                continue
            if not utt.get("remote_comment_id"):
                storage.mark_utterance_synced(cfg.db_path, utt["id"], str(comment_id))
            client.update_comment(comment_id, author_name=f"회의_{utt['speaker']}")
            updated += 1
    except G5ApiError as e:
        print(f"업데이트 실패: {e}", file=sys.stderr)
        return 4

    print(f"✓ {updated}건 업데이트 완료" + (f" ({skipped}건 스킵)" if skipped else ""))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/update_comment_authors.py <meeting_id>")
        sys.exit(1)
    sys.exit(main(int(sys.argv[1])))
