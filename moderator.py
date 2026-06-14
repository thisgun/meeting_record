"""게시판 AI 모더레이터 / 자동 태깅 데몬.

그누보드5 게시판(MOD_BOARDS)을 폴링하며 새 글·댓글을:
  - Ollama로 스팸/광고/욕설/정상 분류
  - 문제 글: 관리자 신고 게시판에 리포트(+옵션: 비밀글로 자동 숨김)
  - 정상 긴 글: 3줄 요약 + 검색 태그를 봇 댓글로 추가

처리 상태는 meetings.db의 moderation 테이블에 기록해 중복 처리를 막는다.

사용:
    python moderator.py            # 폴링 시작 (Ctrl+C 종료)
    python moderator.py --once     # 한 번만 확인

설정 (.env): MOD_BOARDS, MOD_REPORT_BOARD, MOD_AUTO_HIDE, MOD_HIDE_THRESHOLD,
            MOD_SUMMARY_MIN_CHARS, MOD_MODERATE_COMMENTS, MOD_POLL_SEC, MOD_BOT_NAME
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import load_config
from src.g5_client import G5ApiError, G5MeetingApiClient, _public_post_url_from_api_base
from src.moderator import CATEGORY_LABEL_KO, classify_content, summarize_and_tag
from src.storage import connect


PROJECT_ROOT = Path(__file__).resolve().parent
MOD_LOG = PROJECT_ROOT / "data" / "moderator.log"

MOD_SCHEMA = """
CREATE TABLE IF NOT EXISTS moderation (
    bo_table TEXT NOT NULL,
    wr_id INTEGER NOT NULL,
    is_comment INTEGER NOT NULL DEFAULT 0,
    category TEXT,
    confidence REAL,
    reason TEXT,
    action TEXT,
    report_wr_id INTEGER,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (bo_table, wr_id, is_comment)
);
"""


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        MOD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with MOD_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def init_mod_schema(db_path) -> None:
    with connect(db_path) as conn:
        conn.executescript(MOD_SCHEMA)


def is_moderated(db_path, bo_table: str, wr_id: int, is_comment: int) -> bool:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM moderation WHERE bo_table=? AND wr_id=? AND is_comment=?",
            (bo_table, int(wr_id), int(is_comment)),
        ).fetchone() is not None


def mark(db_path, bo_table: str, wr_id: int, is_comment: int, *,
         category: str, confidence: float, reason: str, action: str,
         report_wr_id: int | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO moderation
                 (bo_table, wr_id, is_comment, category, confidence, reason, action,
                  report_wr_id, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(bo_table, wr_id, is_comment) DO UPDATE SET
                 category=excluded.category, confidence=excluded.confidence,
                 reason=excluded.reason, action=excluded.action,
                 report_wr_id=excluded.report_wr_id, processed_at=excluded.processed_at""",
            (bo_table, int(wr_id), int(is_comment), category, float(confidence),
             (reason or "")[:500], action, report_wr_id, now),
        )


def _post_url(cfg, bo_table: str, wr_id: int) -> str:
    try:
        return _public_post_url_from_api_base(cfg.g5_api_base, bo_table, int(wr_id))
    except Exception:
        return ""


def format_report(cfg, *, bo_table: str, wr_id: int, is_comment: int,
                  cls: dict, name: str, snippet: str) -> tuple[str, str]:
    label = CATEGORY_LABEL_KO.get(cls["category"], cls["category"])
    kind = "댓글" if is_comment else "게시글"
    subject = f"[자동신고] {label} · {bo_table} {kind} #{wr_id}"
    url = _post_url(cfg, bo_table, wr_id)
    lines = [
        f"## 🚨 자동 모더레이션 신고",
        f"- 분류: **{label}** (신뢰도 {cls['confidence']:.2f})",
        f"- 위치: {bo_table} {kind} #{wr_id}" + (f" — {url}" if url and not is_comment else ""),
        f"- 작성자: {name or '(미상)'}",
        f"- 근거: {cls.get('reason') or '(없음)'}",
        "",
        "### 원문 일부",
        f"> {snippet[:300]}",
    ]
    return subject, "\n".join(lines)


def format_tag_comment(st: dict) -> str:
    lines = ["🤖 **AI 요약**", st["summary"].strip() or "(요약 없음)"]
    if st["tags"]:
        lines.append("")
        lines.append("🏷 " + " ".join(f"#{t}" for t in st["tags"]))
    return "\n".join(lines)


def moderate_item(cfg, client: G5MeetingApiClient, *, bo_table: str, wr_id: int,
                  is_comment: int, subject: str, content: str, name: str) -> str:
    text = f"{subject}\n{strip_html(content)}".strip()
    body_only = strip_html(content)
    cls = classify_content(
        text, model=cfg.mod_model, host=cfg.ollama_host,
        timeout=cfg.ollama_timeout_sec, keep_alive=cfg.ollama_keep_alive,
        num_ctx_max=cfg.ollama_num_ctx_max, num_gpu=cfg.ollama_num_gpu,
    )
    cat, conf = cls["category"], cls["confidence"]
    actions: list[str] = []
    report_wr_id = None

    if cat != "normal":
        if cfg.mod_report_board:
            try:
                subj, body = format_report(
                    cfg, bo_table=bo_table, wr_id=wr_id, is_comment=is_comment,
                    cls=cls, name=name, snippet=body_only or subject,
                )
                res = client.create_post(subj, body, bo_table=cfg.mod_report_board)
                report_wr_id = int(res.get("wr_id") or 0)
                actions.append("reported")
            except G5ApiError as e:
                log(f"    신고 등록 실패: {e}")
        # 자동 숨김: 원글만, 충분히 확실할 때
        if cfg.mod_auto_hide and not is_comment and conf >= cfg.mod_hide_threshold:
            try:
                client.hide_post(wr_id, bo_table=bo_table, hidden=True)
                actions.append("hidden")
            except G5ApiError as e:
                log(f"    숨김 실패: {e}")
    else:
        # 정상 긴 글에 요약·태그 (원글만)
        if not is_comment and len(body_only) >= cfg.mod_summary_min_chars:
            st = summarize_and_tag(
                text, model=cfg.mod_model, host=cfg.ollama_host,
                timeout=cfg.ollama_timeout_sec, keep_alive=cfg.ollama_keep_alive,
                num_ctx_max=cfg.ollama_num_ctx_max, num_gpu=cfg.ollama_num_gpu,
            )
            if st["summary"] or st["tags"]:
                try:
                    client.create_comment(
                        wr_id, format_tag_comment(st),
                        bo_table=bo_table, author_name=cfg.mod_bot_name,
                    )
                    actions.append("tagged")
                except G5ApiError as e:
                    log(f"    요약 댓글 실패: {e}")

    action = "+".join(actions) or "ok"
    mark(cfg.db_path, bo_table, wr_id, is_comment,
         category=cat, confidence=conf, reason=cls.get("reason", ""),
         action=action, report_wr_id=report_wr_id)
    label = CATEGORY_LABEL_KO.get(cat, cat)
    kind = "댓글" if is_comment else "글"
    log(f"  {kind} #{wr_id}: {label}({conf:.2f}) → {action}")
    return action


def poll_once(cfg, client: G5MeetingApiClient, *, page_size: int = 50) -> int:
    init_mod_schema(cfg.db_path)
    handled = 0
    for bo in cfg.mod_boards:
        if bo == cfg.mod_report_board:
            continue  # 신고 게시판 자체는 모더레이션 제외
        offset = 0
        while True:
            try:
                data = client.list_posts(bo, offset=offset, limit=page_size)
            except G5ApiError as e:
                log(f"  '{bo}' 글 조회 실패: {e}")
                break
            posts = data.get("posts", [])
            if not posts:
                break
            for p in posts:
                wr_id = int(p["wr_id"])
                # 봇이 쓴 글(신고/요약)은 건너뜀
                if (p.get("name") or "") == cfg.mod_bot_name:
                    continue
                if not is_moderated(cfg.db_path, bo, wr_id, 0):
                    moderate_item(cfg, client, bo_table=bo, wr_id=wr_id, is_comment=0,
                                  subject=p.get("subject", ""), content=p.get("content", ""),
                                  name=p.get("name", ""))
                    handled += 1
                if cfg.mod_moderate_comments and int(p.get("comment_count") or 0) > 0:
                    try:
                        comments = client.list_comments(wr_id, bo_table=bo)
                    except G5ApiError:
                        comments = []
                    for c in comments:
                        cid = int(c.get("comment_id") or 0)
                        if not cid or (c.get("author_name") or "") == cfg.mod_bot_name:
                            continue
                        if not is_moderated(cfg.db_path, bo, cid, 1):
                            moderate_item(cfg, client, bo_table=bo, wr_id=cid, is_comment=1,
                                          subject="", content=c.get("content", ""),
                                          name=c.get("author_name", ""))
                            handled += 1
            offset += len(posts)
            if offset >= int(data.get("total", 0)):
                break
    return handled


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="게시판 AI 모더레이터 / 자동 태깅 데몬")
    parser.add_argument("--once", action="store_true", help="한 번만 확인하고 종료")
    args = parser.parse_args(argv)

    cfg = load_config()
    if not cfg.g5_api_base or not cfg.g5_api_token:
        print("[error] .env의 G5_API_BASE/G5_API_TOKEN을 설정하세요.", file=sys.stderr)
        return 3
    client = G5MeetingApiClient(
        api_base=cfg.g5_api_base, api_token=cfg.g5_api_token, name="moderator",
    )

    log("=" * 60)
    log("moderator 시작")
    log(f"대상 게시판: {', '.join(cfg.mod_boards)}")
    log(f"신고 게시판: {cfg.mod_report_board or '(없음 — DB 기록만)'}")
    log(f"자동 숨김: {'ON' if cfg.mod_auto_hide else 'OFF'} (임계 {cfg.mod_hide_threshold})")
    log(f"요약·태그 최소 길이: {cfg.mod_summary_min_chars}자 / 댓글 모더레이션: {cfg.mod_moderate_comments}")
    log(f"분류 모델: {cfg.mod_model} / 폴링: {cfg.mod_poll_sec}초")
    log("=" * 60)

    from src.notifier import notify_alert

    alerted = False  # 폴링 오류 알림 중복 방지
    try:
        while True:
            try:
                n = poll_once(cfg, client)
                if n:
                    log(f"이번 폴링에서 {n}건 처리")
                if alerted:
                    notify_alert("moderator 복구됨", "게시판 모더레이션 폴링이 정상화되었습니다.", success=True)
                    alerted = False
            except Exception as e:
                log(f"폴링 오류: {e}")
                if not alerted:
                    notify_alert("moderator 폴링 오류",
                                 f"게시판 모더레이션 폴링이 실패했습니다. Ollama/그누보드 상태를 확인하세요.\n{e}")
                    alerted = True
            if args.once:
                break
            time.sleep(cfg.mod_poll_sec)
    except KeyboardInterrupt:
        log("종료 신호 수신")
    log("moderator 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
