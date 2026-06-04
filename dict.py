"""도메인 사전 CLI.

사용:
    python dict.py add 산업안전                                        # Whisper에게 알릴 용어만 등록
    python dict.py add 산업안전 --pattern 산업안정                      # 잘못 인식된 "산업안정"을 "산업안전"으로 자동 치환
    python dict.py add 이민재 --pattern "(?:이민자|이민제)"            # 정규식 매칭
    python dict.py list                                                # 등록된 모든 용어
    python dict.py list --scope global                                 # 특정 scope만
    python dict.py delete <id>
    python dict.py enable <id> / disable <id>
    python dict.py import-csv samples/dictionary.csv                   # CSV 일괄 등록
    python dict.py test "산업안정 강화 회의"                            # 치환 결과 미리보기
    python dict.py prompt                                              # Whisper용 initial_prompt 미리보기
    python dict.py apply-to-meeting <meeting_id>                       # 기존 회의에 사전 적용 (DB+그누보드5 갱신)

CSV 포맷 (헤더 필수):
    term,pattern,replacement,notes
    산업안전,산업안정,,자주 틀림
    중대재해,중대제해,,
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from src import dictionary as d


def _row_short(r: dict) -> str:
    flag = "✓" if r["enabled"] else "✗"
    pattern = r["pattern"] or "—"
    repl = r["replacement"] or (r["term"] if r["pattern"] else "—")
    notes = f" ({r['notes']})" if r["notes"] else ""
    return f"{flag} #{r['id']:>4} [{r['scope']}] term={r['term']!r} pattern={pattern!r} → {repl!r}{notes}"


def cmd_add(args) -> int:
    cfg = load_config()
    res = d.add_term(
        cfg.db_path,
        args.term,
        pattern=args.pattern,
        replacement=args.replacement,
        scope=args.scope,
        notes=args.notes,
    )
    print(f"✓ {res['action']}: id={res['id']}, term={res['term']!r}")
    return 0


def cmd_list(args) -> int:
    cfg = load_config()
    rows = d.list_all(cfg.db_path, scope=args.scope)
    if not rows:
        print("등록된 용어 없음")
        return 0
    print(f"\n등록된 용어 {len(rows)}개\n")
    for r in rows:
        print(" " + _row_short(r))
    return 0


def cmd_delete(args) -> int:
    cfg = load_config()
    n = d.remove_term(cfg.db_path, args.id)
    if n:
        print(f"✓ id={args.id} 삭제 완료")
        return 0
    print(f"id={args.id} 없음", file=sys.stderr)
    return 1


def cmd_enable(args) -> int:
    cfg = load_config()
    n = d.set_enabled(cfg.db_path, args.id, True)
    print(f"✓ id={args.id} 활성화" if n else f"id={args.id} 없음")
    return 0 if n else 1


def cmd_disable(args) -> int:
    cfg = load_config()
    n = d.set_enabled(cfg.db_path, args.id, False)
    print(f"✓ id={args.id} 비활성화" if n else f"id={args.id} 없음")
    return 0 if n else 1


def cmd_test(args) -> int:
    cfg = load_config()
    result = d.apply_replacements(cfg.db_path, args.text, scope=args.scope)
    print(f"입력: {args.text}")
    print(f"출력: {result}")
    if result == args.text:
        print("(변경 없음)")
    return 0


def cmd_prompt(args) -> int:
    cfg = load_config()
    prompt = d.build_whisper_prompt(cfg.db_path, scope=args.scope)
    if prompt:
        print(f"Whisper initial_prompt ({len(prompt)}자):")
        print(f"  {prompt}")
    else:
        print("등록된 용어 없음 → initial_prompt 사용 안 함")
    return 0


def cmd_import(args) -> int:
    cfg = load_config()
    n = d.import_csv(cfg.db_path, args.csv, scope=args.scope)
    print(f"✓ {n}개 등록/갱신")
    return 0


def cmd_apply_to_meeting(args) -> int:
    """기존 회의의 발화/요약에 사전 치환 적용 + 그누보드5 갱신."""
    import json
    from src import cache, storage
    from src.g5_client import G5ApiError, build_clients_from_env, format_utterance_comment

    cfg = load_config()
    meeting = storage.get_meeting(cfg.db_path, args.meeting_id)
    if not meeting:
        print(f"meeting_id={args.meeting_id} 없음", file=sys.stderr)
        return 1

    # 1) 발화 치환
    utts = meeting["utterances"]
    seg_dicts = [{
        "id": u["id"],
        "speaker": u["speaker"],
        "start": u["start_sec"],
        "end": u["end_sec"],
        "text": u["text"],
    } for u in utts]
    new_segs, n_changed = d.apply_to_segments(cfg.db_path, seg_dicts)
    print(f"발화 {len(utts)}건 중 {n_changed}건 텍스트 변경")

    # 2) 요약 치환
    old_title = meeting["meeting"]["title"]
    old_md = meeting["meeting"]["summary_md"]
    new_title = d.apply_replacements(cfg.db_path, old_title)
    new_md = d.apply_replacements(cfg.db_path, old_md)
    title_changed = new_title != old_title
    md_changed = new_md != old_md

    if n_changed == 0 and not title_changed and not md_changed:
        print("변경 사항 없음")
        return 0

    # 3) SQLite 업데이트
    if title_changed or md_changed:
        storage.update_meeting_summary(
            cfg.db_path,
            args.meeting_id,
            title=new_title,
            summary_md=new_md,
        )
    for orig, new in zip(utts, new_segs):
        if orig["text"] != new["text"]:
            storage.update_utterance_text(cfg.db_path, orig["id"], new["text"])
    print("✓ SQLite 갱신")

    # 4) 그누보드5도 갱신 (직접 MySQL 대신 HTTP API 사용)
    if not args.skip_remote and (meeting["meeting"]["remote_post_id"] or meeting.get("sync_targets")):
        clients = build_clients_from_env(cfg)
        if not clients:
            print("[warn] G5 클라이언트 없음 — 원격 갱신 생략", file=sys.stderr)
        else:
            remote_updates = 0
            remote_failed = False
            for client in clients:
                target = storage.get_meeting_target(cfg.db_path, args.meeting_id, client.name)
                target_wr_id = target.get("remote_post_id") if target else None
                if not target_wr_id and client.name == "default":
                    target_wr_id = meeting["meeting"].get("remote_post_id")
                if not target_wr_id:
                    print(f"[warn] [{client.name}] 원격 게시글 ID 없음 — 스킵", file=sys.stderr)
                    continue
                wr_id = int(target_wr_id)
                print(f"그누보드5 갱신 대상: [{client.name}] {client.api_base}")
                try:
                    target_updates = 0
                    comments = []
                    needs_comment_lookup = any(
                        orig["text"] != new["text"]
                        and not (storage.get_utterance_target(cfg.db_path, orig["id"], client.name) or {}).get("remote_comment_id")
                        for orig, new in zip(utts, new_segs)
                    )
                    if needs_comment_lookup:
                        comments = client.list_comments(wr_id)
                        if len(comments) != len(utts):
                            print(
                                f"[warn] [{client.name}] 원격 댓글 수({len(comments)})와 로컬 발화 수({len(utts)})가 달라 순서 매핑이 부정확할 수 있음",
                                file=sys.stderr,
                            )
                            comments = []

                    if title_changed or md_changed:
                        client.update_post(
                            wr_id,
                            subject=new_title if title_changed else None,
                            content=new_md if md_changed else None,
                        )
                        target_updates += 1

                    for idx, (orig, new) in enumerate(zip(utts, new_segs)):
                        if orig["text"] == new["text"]:
                            continue
                        utt_target = storage.get_utterance_target(cfg.db_path, orig["id"], client.name)
                        comment_id = (utt_target or {}).get("remote_comment_id")
                        if not comment_id and idx < len(comments):
                            comment_id = comments[idx].get("comment_id")
                            if comment_id:
                                storage.mark_utterance_synced(
                                    cfg.db_path,
                                    orig["id"],
                                    str(comment_id),
                                    target_name=client.name,
                                    primary=False,
                                )
                        if not comment_id:
                            print(f"[warn] [{client.name}] 발화 id={orig['id']}의 원격 댓글 ID를 찾지 못해 스킵", file=sys.stderr)
                            continue
                        utt_for_comment = {
                            "speaker": new["speaker"],
                            "start": new["start"],
                            "end": new["end"],
                            "text": new["text"],
                        }
                        client.update_comment(
                            int(comment_id),
                            content=format_utterance_comment(utt_for_comment),
                        )
                        target_updates += 1
                    remote_updates += target_updates
                    print(f"✓ [{client.name}] wr_id={wr_id} 갱신 ({target_updates}건)")
                except G5ApiError as e:
                    remote_failed = True
                    print(f"[error] [{client.name}] 그누보드5 갱신 실패: {e}", file=sys.stderr)
            if remote_failed:
                return 2
            if remote_updates:
                print(f"✓ 그누보드5 전체 갱신 ({remote_updates}건)")

    # 5) 캐시 파일도 갱신
    src_file = meeting["meeting"]["source_file"]
    cache_path = cache.segments_cache_path(src_file, cfg.work_dir)
    if cache_path.exists():
        cache_path.write_text(json.dumps([
            {"start": s["start"], "end": s["end"], "speaker": s["speaker"], "text": s["text"]}
            for s in new_segs
        ], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ 캐시 갱신: {cache_path.name}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="도메인 사전 CLI", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="용어 등록")
    p.add_argument("term", help="정확한 표기 (Whisper 컨텍스트용)")
    p.add_argument("--pattern", help="후처리 매칭 정규식 (선택)")
    p.add_argument("--replacement", help="치환 텍스트 (선택, 기본은 term)")
    p.add_argument("--scope", default="global")
    p.add_argument("--notes", help="설명")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="등록된 용어 목록")
    p.add_argument("--scope")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", help="용어 삭제")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("enable", help="활성화")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_enable)

    p = sub.add_parser("disable", help="비활성화")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser("test", help="입력 텍스트에 치환 미리보기")
    p.add_argument("text")
    p.add_argument("--scope", default="global")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("prompt", help="Whisper initial_prompt 미리보기")
    p.add_argument("--scope", default="global")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("import-csv", help="CSV 일괄 등록")
    p.add_argument("csv")
    p.add_argument("--scope", default="global")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("apply-to-meeting", help="기존 회의에 사전 치환 적용 (DB+그누보드5 갱신)")
    p.add_argument("meeting_id", type=int)
    p.add_argument("--skip-remote", action="store_true", help="그누보드5 갱신 생략 (로컬 DB만)")
    p.set_defaults(func=cmd_apply_to_meeting)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
