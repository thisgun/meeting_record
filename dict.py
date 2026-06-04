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
    import subprocess
    import tempfile
    from src import storage

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
    import sqlite3
    with sqlite3.connect(str(cfg.db_path)) as conn:
        if title_changed or md_changed:
            conn.execute(
                "UPDATE meetings SET title=?, summary_md=? WHERE id=?",
                (new_title, new_md, args.meeting_id),
            )
        for orig, new in zip(utts, new_segs):
            if orig["text"] != new["text"]:
                conn.execute("UPDATE utterances SET text=? WHERE id=?", (new["text"], orig["id"]))
    print("✓ SQLite 갱신")

    # 4) 그누보드5도 갱신
    if not args.skip_remote and meeting["meeting"]["remote_post_id"]:
        wr_id = int(meeting["meeting"]["remote_post_id"])
        mysql = r"C:\xampp\mysql\bin\mysql.exe"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
            sql_path = f.name
            if title_changed or md_changed:
                esc_t = new_title.replace("\\", "\\\\").replace("'", "''")
                esc_c = new_md.replace("\\", "\\\\").replace("'", "''")
                f.write(f"UPDATE g5_write_meeting SET wr_subject='{esc_t}', wr_content='{esc_c}' WHERE wr_id={wr_id};\n")
            # 댓글들도 ORDER BY wr_id로 매핑 가능
            f.write(f"-- comments will be matched in Python loop\n")

        # 댓글은 Python에서 처리 (개수/순서 정밀 매칭)
        if n_changed > 0:
            result = subprocess.run(
                [mysql, "-u", "root", "meeting", "-N", "-B", "-e",
                 f"SELECT wr_id FROM g5_write_meeting WHERE wr_parent={wr_id} AND wr_is_comment=1 ORDER BY wr_id"],
                capture_output=True, text=True, encoding="utf-8",
            )
            comment_ids = [int(x) for x in result.stdout.strip().split("\n") if x]
            updates = []
            for cid, orig, new in zip(comment_ids, utts, new_segs):
                if orig["text"] != new["text"]:
                    # 댓글 본문은 "[mm:ss] 사용자N: 텍스트" 형식. 텍스트 부분만 치환.
                    # 안전하게 새 본문 전체를 만들어 갱신.
                    mm, sec = divmod(int(new["start"]), 60)
                    new_content = f"[{mm:02d}:{sec:02d}] {new['speaker']}: {new['text']}"
                    esc = new_content.replace("\\", "\\\\").replace("'", "''")
                    updates.append(f"UPDATE g5_write_meeting SET wr_content='{esc}' WHERE wr_id={cid};")
            with open(sql_path, "a", encoding="utf-8") as f:
                f.write("\n".join(updates))

        subprocess.run(
            [mysql, "-u", "root", "meeting", "--default-character-set=utf8mb4"],
            stdin=open(sql_path, encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8",
        )
        Path(sql_path).unlink(missing_ok=True)
        print(f"✓ 그누보드5 wr_id={wr_id} 갱신 (게시글 + 댓글 {n_changed}건)")

    # 5) 캐시 파일도 갱신
    src_file = meeting["meeting"]["source_file"]
    cache_name = Path(src_file).stem + ".segments.json"
    cache_path = cfg.work_dir / cache_name
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
