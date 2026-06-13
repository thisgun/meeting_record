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

import requests

from config import load_config
from src.embeddings import index_all
from src.g5_client import G5MettingApiClient
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
    PRIMARY KEY (bo_table, wr_id)
);
"""


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


def last_seen_wr_id(db_path, bo_table: str) -> int:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(wr_id) FROM qa_answers WHERE bo_table = ?", (bo_table,)
        ).fetchone()
        return int(row[0] or 0)


def mark(db_path, bo_table: str, wr_id: int, *, status: str,
         comment_id: int | None = None, error: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO qa_answers (bo_table, wr_id, comment_id, status, error, answered_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(bo_table, wr_id) DO UPDATE SET
                 comment_id = excluded.comment_id,
                 status = excluded.status,
                 error = excluded.error,
                 answered_at = excluded.answered_at""",
            (bo_table, int(wr_id), comment_id, status,
             (error or "")[:2000] or None, now),
        )


def failed_wr_ids(db_path, bo_table: str) -> list[int]:
    with connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT wr_id FROM qa_answers WHERE bo_table = ? AND status = 'failed' ORDER BY wr_id",
            (bo_table,),
        )]


def fetch_questions(cfg, *, since_wr_id: int, limit: int = 20) -> list[dict]:
    url = f"{cfg.g5_api_base}/questions.php"
    r = requests.get(
        url,
        params={"bo_table": cfg.qa_bo_table, "since_wr_id": since_wr_id, "limit": limit},
        headers={"X-API-Token": cfg.g5_api_token},
        timeout=30,
    )
    data = r.json()
    if r.status_code >= 400 or not data.get("ok"):
        raise RuntimeError(f"questions.php 실패: HTTP {r.status_code}: {data.get('error') or data}")
    return data.get("questions", [])


def answer_one(cfg, client: G5MettingApiClient, q: dict) -> None:
    """질문 1건 처리: RAG 답변 생성 → 댓글 등록 → 상태 기록."""
    wr_id = int(q["wr_id"])
    bo = cfg.qa_bo_table
    subject = (q.get("subject") or "").strip()
    body = strip_html(q.get("content") or "")
    question = f"{subject}\n{body}".strip()[:MAX_QUESTION_CHARS]

    log(f"  질문 #{wr_id} ({q.get('name')}): {subject[:60]}")
    mark(cfg.db_path, bo, wr_id, status="processing")
    try:
        result = answer_question(cfg, question, auto_index=False)
        answer_md = result["answer_with_sources"]
        res = client.create_comment(wr_id, answer_md, bo_table=bo, author_name=QA_BOT_NAME)
        comment_id = int(res.get("comment_id") or 0)
        mark(cfg.db_path, bo, wr_id, status="done", comment_id=comment_id)
        log(f"  ✓ 답변 등록: #{wr_id} → 댓글 {comment_id} (출처 {len(result['sources'])}건)")
    except Exception as e:
        mark(cfg.db_path, bo, wr_id, status="failed", error=str(e))
        log(f"  ✗ 답변 실패: #{wr_id} - {e}")


def poll_once(cfg, client: G5MettingApiClient, *, retry_failed: bool = False) -> int:
    """한 번 폴링. 처리한 질문 수 반환."""
    init_qa_schema(cfg.db_path)

    targets: list[dict] = []
    if retry_failed:
        retry_ids = set(failed_wr_ids(cfg.db_path, cfg.qa_bo_table))
        if retry_ids:
            # 전체 목록에서 실패분을 다시 가져옴
            all_q = fetch_questions(cfg, since_wr_id=0, limit=100)
            targets.extend(q for q in all_q if int(q["wr_id"]) in retry_ids)

    since = last_seen_wr_id(cfg.db_path, cfg.qa_bo_table)
    targets.extend(fetch_questions(cfg, since_wr_id=since))

    if not targets:
        return 0

    # 새 회의록이 있으면 답변 전에 인덱싱
    n = index_all(cfg.db_path, embed_model=cfg.embed_model, host=cfg.ollama_host, verbose=False)
    if n:
        log(f"  새 회의 {n}건 인덱싱")

    for q in targets:
        answer_one(cfg, client, q)
    return len(targets)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="회의록 Q&A 게시판 자동 답변 데몬")
    parser.add_argument("--once", action="store_true", help="한 번만 확인하고 종료")
    parser.add_argument("--retry-failed", action="store_true", help="실패했던 질문 재시도")
    args = parser.parse_args(argv)

    cfg = load_config()
    client = G5MettingApiClient(
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

    retry = args.retry_failed
    try:
        while True:
            try:
                handled = poll_once(cfg, client, retry_failed=retry)
                retry = False  # 재시도는 첫 폴링에서만
                if handled:
                    log(f"이번 폴링에서 {handled}건 처리")
            except Exception as e:
                log(f"폴링 오류: {e}")
            if args.once:
                break
            time.sleep(cfg.qa_poll_sec)
    except KeyboardInterrupt:
        log("종료 신호 수신")
    log("qa_watcher 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
