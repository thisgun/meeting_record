"""회의록 RAG 질의응답.

질문 → 벡터 검색(embeddings.py) + FTS5 보조 검색 → Ollama LLM이
회의록 근거 기반으로 답변 생성. 출처(회의 제목/날짜/게시글 링크) 포함.

사용:
    from src.rag import answer_question
    result = answer_question(cfg, "지난달 예산 회의에서 뭐 결정했지?")
    print(result["answer"])       # 마크다운 답변
    print(result["sources"])      # [{meeting_id, title, created_at, url}, ...]
"""
from __future__ import annotations

import re

from .embeddings import search_chunks, index_all
from .storage import connect


ANSWER_SYSTEM_PROMPT = """당신은 회의록 검색 비서입니다. 아래 제공되는 회의록 발췌(출처 번호 포함)만 근거로 사용자의 질문에 한국어로 답하십시오.

**규칙:**
1. 발췌에 있는 내용만 사용하십시오. 발췌에 없는 내용은 추측하지 말고 "회의록에서 관련 내용을 찾지 못했습니다"라고 답하십시오.
2. 답변 중 근거가 된 부분에는 출처 번호를 [출처 1]처럼 표기하십시오.
3. 구체적인 숫자, 날짜, 담당자, 결정사항을 발췌 그대로 인용하십시오.
4. 답변은 간결한 마크다운으로: 핵심 답변 1~3문장 → 필요 시 상세 bullet.
5. 여러 회의에 걸친 내용이면 회의별로 구분해서 정리하십시오."""


def _fts_query_from_question(question: str) -> str | None:
    """질문에서 FTS5 trigram MATCH 쿼리 생성 (3자 이상 토큰 OR 결합)."""
    tokens = re.findall(r"[0-9A-Za-z가-힣]{3,}", question)
    tokens = list(dict.fromkeys(tokens))[:8]  # 중복 제거, 최대 8개
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


def _fts_supplement(db_path, question: str, *, limit: int = 4) -> list[dict]:
    """FTS5 발화 검색으로 벡터 검색을 보완 (키워드 정확 일치에 강함)."""
    match = _fts_query_from_question(question)
    if not match:
        return []
    sql = """
    SELECT u.meeting_id, u.speaker, u.start_sec, u.text,
           m.title, m.created_at, m.remote_post_id
    FROM utterances_fts
    JOIN utterances u ON u.id = utterances_fts.rowid
    JOIN meetings m ON m.id = u.meeting_id
    WHERE utterances_fts MATCH ?
    ORDER BY bm25(utterances_fts) LIMIT ?
    """
    try:
        with connect(db_path) as conn:
            rows = conn.execute(sql, (match, int(limit))).fetchall()
    except Exception:
        return []  # FTS 쿼리 문법 오류 등은 무시 (벡터 검색이 주력)
    return [{
        "meeting_id": r["meeting_id"],
        "kind": "utterance",
        "start_sec": r["start_sec"],
        "text": f"[회의: {r['title']}]\n{r['speaker']}: {r['text']}",
        "score": 0.0,
        "title": r["title"],
        "created_at": r["created_at"],
        "remote_post_id": r["remote_post_id"],
    } for r in rows]


def retrieve(
    db_path,
    question: str,
    *,
    embed_model: str,
    host: str,
    top_k: int = 6,
    max_context_chars: int = 8000,
) -> list[dict]:
    """벡터 + FTS 하이브리드 검색. 컨텍스트 길이 제한 내에서 청크 반환."""
    hits = search_chunks(db_path, question, embed_model=embed_model, host=host, top_k=top_k)
    seen_texts = {h["text"] for h in hits}
    for h in _fts_supplement(db_path, question):
        if h["text"] not in seen_texts:
            hits.append(h)
            seen_texts.add(h["text"])

    out, total = [], 0
    for h in hits:
        if total + len(h["text"]) > max_context_chars and out:
            break
        out.append(h)
        total += len(h["text"])
    return out


def _format_timestamp(sec) -> str:
    if sec is None:
        return ""
    mm, ss = divmod(int(float(sec)), 60)
    return f" {mm:02d}:{ss:02d}~"


def _board_root_from_api_base(api_base: str) -> str:
    """G5_API_BASE(.../plugin/meeting_api) → 그누보드5 루트 URL."""
    return re.sub(r"/plugin/[^/]+/?$", "", api_base.rstrip("/"))


def post_url(api_base: str, bo_table: str, wr_id) -> str | None:
    if not (api_base and wr_id):
        return None
    root = _board_root_from_api_base(api_base)
    return f"{root}/bbs/board.php?bo_table={bo_table}&wr_id={wr_id}"


def build_context(hits: list[dict]) -> tuple[str, list[dict]]:
    """청크 → LLM 컨텍스트 텍스트 + 출처 목록(회의 단위 dedupe)."""
    blocks = []
    sources: list[dict] = []
    src_no_by_meeting: dict[int, int] = {}
    for h in hits:
        mid = h["meeting_id"]
        if mid not in src_no_by_meeting:
            src_no_by_meeting[mid] = len(src_no_by_meeting) + 1
            sources.append({
                "no": src_no_by_meeting[mid],
                "meeting_id": mid,
                "title": h["title"],
                "created_at": (h["created_at"] or "")[:10],
                "remote_post_id": h["remote_post_id"],
            })
        no = src_no_by_meeting[mid]
        kind = "요약" if h["kind"] == "summary" else "발화"
        ts = _format_timestamp(h["start_sec"]) if h["kind"] == "utterance" else ""
        blocks.append(
            f"[출처 {no}] 회의 \"{h['title']}\" ({(h['created_at'] or '')[:10]}, {kind}{ts})\n{h['text']}"
        )
    return "\n\n---\n\n".join(blocks), sources


def generate_answer(
    question: str,
    context: str,
    *,
    model: str,
    host: str,
    timeout: float = 600.0,
) -> str:
    try:
        from ollama import Client
    except ImportError as e:
        raise RuntimeError("ollama 패키지가 필요합니다: pip install ollama") from e

    client = Client(host=host, timeout=timeout)
    user_msg = (
        f"## 회의록 발췌\n\n{context}\n\n"
        f"## 질문\n\n{question}\n\n"
        "위 발췌만 근거로 답변하십시오."
    )
    approx_tokens = int(len(user_msg) * 0.5) + 2048
    num_ctx = min(131072, max(4096, ((approx_tokens // 1024) + 1) * 1024))

    resp = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        options={"temperature": 0.2, "num_ctx": num_ctx, "num_predict": 4096},
        keep_alive="60m",
    )
    content = resp.get("message", {}).get("content", "") if isinstance(resp, dict) \
        else resp.message.content
    return (content or "").strip()


def format_sources_footer(sources: list[dict], *, api_base: str, bo_table: str) -> str:
    """답변 하단에 붙일 출처 목록 (게시글 링크 포함)."""
    if not sources:
        return ""
    lines = ["", "---", "**참고한 회의록:**"]
    for s in sources:
        url = post_url(api_base, bo_table, s["remote_post_id"])
        link = f" → {url}" if url else ""
        lines.append(f"- [출처 {s['no']}] {s['title']} ({s['created_at']}){link}")
    return "\n".join(lines)


def answer_question(
    cfg,
    question: str,
    *,
    auto_index: bool = True,
    top_k: int | None = None,
) -> dict:
    """질문 1건 처리. {answer, answer_with_sources, sources, hits} 반환."""
    question = (question or "").strip()
    if not question:
        raise ValueError("질문이 비어 있습니다")

    if auto_index:
        index_all(cfg.db_path, embed_model=cfg.embed_model, host=cfg.ollama_host,
                  verbose=False)

    hits = retrieve(
        cfg.db_path, question,
        embed_model=cfg.embed_model, host=cfg.ollama_host,
        top_k=top_k or cfg.rag_top_k,
    )
    if not hits:
        answer = "회의록에서 관련 내용을 찾지 못했습니다. (인덱싱된 회의가 없거나 질문과 관련된 회의가 없습니다)"
        return {"answer": answer, "answer_with_sources": answer, "sources": [], "hits": []}

    context, sources = build_context(hits)
    answer = generate_answer(question, context, model=cfg.ollama_model, host=cfg.ollama_host)
    footer = format_sources_footer(sources, api_base=cfg.g5_api_base, bo_table=cfg.g5_bo_table)
    return {
        "answer": answer,
        "answer_with_sources": answer + footer,
        "sources": sources,
        "hits": hits,
    }
