"""회의록 Q&A 게시판 자동 답변 데몬.

그누보드5 질문 게시판(QA_BO_TABLE)을 폴링하다가 새 글이 올라오면
RAG(벡터 검색 + Ollama)로 답변을 생성해 댓글로 등록한다.

사용:
    python qa_watcher.py            # 폴링 시작 (Ctrl+C로 종료)
    python qa_watcher.py --once     # 한 번만 확인하고 종료
    python qa_watcher.py --retry-failed  # 실패했던 질문 재시도 후 폴링

설정 (.env):
    QA_BO_TABLE=ask                 # 질문 게시판
    QA_POLL_SEC=20                  # 폴링 주기(초)
    QA_BOT_NAME=회의록봇            # 답변 댓글 작성자명
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import load_config
from src.embeddings import index_all
from src.g5_client import G5MeetingApiClient
from src.rag import answer_question
from src.storage import connect


PROJECT_ROOT = Path(__file__).resolve().parent
QA_LOG = PROJECT_ROOT / "data" / "qa_watch.log"
QA_BOT_NAME = os.getenv("QA_BOT_NAME", "회의록봇")
MAX_QUESTION_CHARS = 2000

QA_SCHEMA = """
CREATE TABLE IF NOT EXISTS qa_answers (
    bo_table TEXT NOT NULL,
    wr_id INTEGER NOT NULL,
    comment_id INTEGER,
    status TEXT NOT NULL DEFAULT 'processing',  -- processing | done | failed
    error TEXT,
    answered_at TEXT,
    comment_count INTEGER NOT NULL DEFAULT 0,    -- 마지막 처리 시점의 댓글 수 (후속 질문 감지용)
    PRIMARY KEY (bo_table, wr_id)
);
"""

# 최근 N턴(=2N 메시지)만 맥락으로 유지
_MAX_HISTORY_TURNS = 6


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        QA_LOG.parent.mkdir(parents=True, exist_ok=True)
        with QA_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def strip_html(text: str) -> str:
    """그누보드 에디터 HTML → 평문."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def init_qa_schema(db_path) -> None:
    with connect(db_path) as conn:
        conn.executescript(QA_SCHEMA)
        # 기존 테이블 마이그레이션: comment_count 컬럼이 없으면 추가
        cols = {r[1] for r in conn.execute("PRAGMA table_info(qa_answers)")}
        if "comment_count" not in cols:
            conn.execute("ALTER TABLE qa_answers ADD COLUMN comment_count INTEGER NOT NULL DEFAULT 0")


def get_qa_state(db_path, bo_table: str, wr_id: int) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, comment_count FROM qa_answers WHERE bo_table = ? AND wr_id = ?",
            (bo_table, int(wr_id)),
        ).fetchone()
        return dict(row) if row else None


def mark(db_path, bo_table: str, wr_id: int, *, status: str,
         comment_id: int | None = None, error: str | None = None,
         comment_count: int | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO qa_answers (bo_table, wr_id, comment_id, status, error, answered_at, comment_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(bo_table, wr_id) DO UPDATE SET
                 comment_id = COALESCE(excluded.comment_id, qa_answers.comment_id),
                 status = excluded.status,
                 error = excluded.error,
                 answered_at = excluded.answered_at,
                 comment_count = COALESCE(?, qa_answers.comment_count)""",
            (bo_table, int(wr_id), comment_id, status,
             (error or "")[:2000] or None, now, int(comment_count or 0),
             comment_count),
        )


def fetch_questions(client: G5MeetingApiClient, cfg, *, since_wr_id: int, limit: int = 20) -> list[dict]:
    return client.list_questions(cfg.qa_bo_table, since_wr_id=since_wr_id, limit=limit)


def _strip_footer(text: str) -> str:
    """봇 답변에서 출처 footer를 떼어 맥락 히스토리를 간결하게 한다."""
    idx = text.find("\n---\n**참고한 회의록:**")
    return (text[:idx] if idx != -1 else text).strip()


def build_history_from_comments(question_body: str, comments: list[dict]) -> tuple[list[dict], str | None]:
    """글 본문 + 기존 댓글 → (대화 history, 미답변 후속 질문).

    봇 댓글(author=QA_BOT_NAME)은 assistant, 사람 댓글은 user로 본다.
    마지막 발화가 사람이면 그것이 미답변 후속 질문.
    """
    history: list[dict] = [{"role": "user", "content": question_body}]
    for c in comments:
        content = strip_html(c.get("content") or "")
        if not content:
            continue
        if (c.get("author_name") or "") == QA_BOT_NAME:
            history.append({"role": "assistant", "content": _strip_footer(content)})
        else:
            history.append({"role": "user", "content": content})

    if len(history) > 1 and history[-1]["role"] == "user":
        pending = history[-1]["content"]
        return history[:-1], pending
    return history, None


def _post_answer(cfg, client: G5MeetingApiClient, wr_id: int, question: str,
                 history: list[dict] | None, *, prev_comment_count: int) -> bool:
    """RAG 답변 생성 → 댓글 등록 → 상태 기록. 성공 시 True."""
    bo = cfg.qa_bo_table
    mark(cfg.board_db_path, bo, wr_id, status="processing")
    try:
        result = answer_question(cfg, question, auto_index=False, history=history)
        res = client.create_comment(
            wr_id, result["answer_with_sources"], bo_table=bo, author_name=QA_BOT_NAME
        )
        comment_id = int(res.get("comment_id") or 0)
        # 방금 봇 답변 1개가 추가됨 → 다음 폴링에서 재처리하지 않도록 카운트 반영
        mark(cfg.board_db_path, bo, wr_id, status="done", comment_id=comment_id,
             comment_count=prev_comment_count + 1)
        log(f"  ✓ 답변 등록: #{wr_id} → 댓글 {comment_id} (출처 {len(result['sources'])}건)")
        return True
    except Exception as e:
        mark(cfg.board_db_path, bo, wr_id, status="failed", error=str(e))
        log(f"  ✗ 답변 실패: #{wr_id} - {e}")
        return False


def answer_new(cfg, client: G5MeetingApiClient, q: dict) -> bool:
    """새 질문 글 처리."""
    wr_id = int(q["wr_id"])
    subject = (q.get("subject") or "").strip()
    body = strip_html(q.get("content") or "")
    question = f"{subject}\n{body}".strip()[:MAX_QUESTION_CHARS]
    log(f"  질문 #{wr_id} ({q.get('name')}): {subject[:60]}")
    return _post_answer(cfg, client, wr_id, question, None,
                        prev_comment_count=int(q.get("comment_count") or 0))


def answer_followup(cfg, client: G5MeetingApiClient, q: dict) -> bool:
    """이미 답변한 글에 달린 사람 후속 댓글 처리 (게시판 멀티턴)."""
    wr_id = int(q["wr_id"])
    bo = cfg.qa_bo_table
    subject = (q.get("subject") or "").strip()
    body = f"{subject}\n{strip_html(q.get('content') or '')}".strip()
    try:
        comments = client.list_comments(wr_id, bo_table=bo)
    except Exception as e:
        log(f"  후속 확인 실패 #{wr_id}: {e}")
        return False

    history, pending = build_history_from_comments(body, comments)
    if not pending:
        # 사람 후속 없이 봇 답변만 늘어난 경우 — 카운트만 동기화해 재확인을 막는다
        mark(cfg.board_db_path, bo, wr_id, status="done", comment_count=len(comments))
        return False

    if len(history) > _MAX_HISTORY_TURNS * 2:
        history = history[-_MAX_HISTORY_TURNS * 2:]
    log(f"  후속 질문 #{wr_id}: {pending[:60]}")
    return _post_answer(cfg, client, wr_id, pending[:MAX_QUESTION_CHARS], history,
                        prev_comment_count=len(comments))


def poll_once(cfg, client: G5MeetingApiClient, *, retry_failed: bool = False) -> int:
    """한 번 폴링. 새 질문 + 후속 댓글을 처리하고 처리 건수를 반환."""
    init_qa_schema(cfg.board_db_path)

    # 새 회의록이 있으면 답변 전에 인덱싱 (회의록 rag_chunks는 meetings.db)
    n = index_all(cfg.db_path, embed_model=cfg.embed_model, host=cfg.ollama_host, verbose=False)
    if n:
        log(f"  새 회의 {n}건 인덱싱")

    questions = fetch_questions(client, cfg, since_wr_id=0, limit=100)
    handled = 0
    for q in questions:
        wr_id = int(q["wr_id"])
        server_cc = int(q.get("comment_count") or 0)
        state = get_qa_state(cfg.board_db_path, cfg.qa_bo_table, wr_id)
        if state is None:
            handled += answer_new(cfg, client, q)
        elif state["status"] == "failed":
            if retry_failed:
                handled += answer_new(cfg, client, q)
        elif state["status"] == "done" and server_cc > int(state["comment_count"] or 0):
            handled += answer_followup(cfg, client, q)
    return handled


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="회의록 Q&A 게시판 자동 답변 데몬")
    parser.add_argument("--once", action="store_true", help="한 번만 확인하고 종료")
    parser.add_argument("--retry-failed", action="store_true", help="실패했던 질문 재시도")
    args = parser.parse_args(argv)

    cfg = load_config()
    client = G5MeetingApiClient(
        api_base=cfg.g5_api_base, api_token=cfg.g5_api_token,
        bo_table=cfg.qa_bo_table, name="qa",
    )

    log("=" * 60)
    log("qa_watcher 시작")
    log(f"질문 게시판: {cfg.qa_bo_table} @ {cfg.g5_api_base}")
    log(f"임베딩: {cfg.embed_model} / 답변: {cfg.ollama_model}")
    log(f"폴링 주기: {cfg.qa_poll_sec}초")
    log("=" * 60)

    # 시작 시 인덱스 최신화
    n = index_all(cfg.db_path, embed_model=cfg.embed_model, host=cfg.ollama_host, verbose=False)
    if n:
        log(f"시작 인덱싱: 회의 {n}건")

    from src.notifier import notify_alert

    retry = args.retry_failed
    alerted = False  # 폴링 오류 알림 중복 방지 (실패 진입 시 1회, 복구 시 1회)
    try:
        while True:
            try:
                handled = poll_once(cfg, client, retry_failed=retry)
                retry = False  # 재시도는 첫 폴링에서만
                if handled:
                    log(f"이번 폴링에서 {handled}건 처리")
                if alerted:
                    notify_alert("qa_watcher 복구됨", "질문 게시판 폴링이 정상화되었습니다.", success=True)
                    alerted = False
            except Exception as e:
                log(f"폴링 오류: {e}")
                if not alerted:
                    notify_alert("qa_watcher 폴링 오류",
                                 f"질문 게시판 폴링이 실패했습니다. Ollama/그누보드 상태를 확인하세요.\n{e}")
                    alerted = True
            if args.once:
                break
            time.sleep(cfg.qa_poll_sec)
    except KeyboardInterrupt:
        log("종료 신호 수신")
    log("qa_watcher 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
