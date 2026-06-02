"""도메인 사전 — STT 정확도 향상용.

두 가지 역할:
1. **Whisper initial_prompt**: 등록된 용어들을 Whisper에게 미리 알려줌 → 인식 정확도 ↑
2. **후처리 치환**: STT 결과의 흔한 오류를 정규식으로 교정

스키마:
- term: Whisper에게 알릴 용어 (필수)
- pattern: 후처리 시 매칭할 정규식 (선택, 비워두면 치환 안 함)
- replacement: pattern 매칭 시 치환할 텍스트 (선택, 비워두면 term 사용)
- scope: "global" (모든 회의) 또는 "tag:xxx" (특정 회의 유형)
- enabled: True/False

예시:
    add(term="산업안전")                                    # Whisper 컨텍스트에만 사용
    add(term="산업안전", pattern="산업안정")                # 잘못 인식된 "산업안정"을 "산업안전"으로
    add(term="이민재", pattern="(?:이민자|이민제)", replacement="이민재")  # 여러 오인식 패턴
"""
from __future__ import annotations

import csv
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DICT_SCHEMA = """
CREATE TABLE IF NOT EXISTS dictionary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,                  -- 정확한 표기 (Whisper 컨텍스트용)
    pattern TEXT,                        -- 후처리 매칭 정규식 (NULL이면 치환 안 함)
    replacement TEXT,                    -- 치환 텍스트 (NULL이면 term 사용)
    scope TEXT NOT NULL DEFAULT 'global',
    enabled INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(term, pattern, scope)
);
CREATE INDEX IF NOT EXISTS idx_dict_scope_enabled ON dictionary(scope, enabled);
"""


@contextmanager
def _connect(db_path: str | Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_dictionary(db_path: str | Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(DICT_SCHEMA)


def add_term(
    db_path: str | Path,
    term: str,
    *,
    pattern: Optional[str] = None,
    replacement: Optional[str] = None,
    scope: str = "global",
    notes: Optional[str] = None,
) -> dict:
    """사전에 용어 추가/갱신."""
    init_dictionary(db_path)
    term = term.strip()
    if not term:
        raise ValueError("term이 비어있습니다")
    if pattern:
        # 정규식 유효성 검증
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"유효하지 않은 정규식: {e}") from e

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT id FROM dictionary WHERE term=? AND COALESCE(pattern,'')=COALESCE(?,'') AND scope=?",
            (term, pattern, scope),
        )
        row = cur.fetchone()
        if row:
            conn.execute(
                "UPDATE dictionary SET replacement=?, notes=?, enabled=1 WHERE id=?",
                (replacement, notes, row["id"]),
            )
            return {"id": row["id"], "term": term, "action": "updated"}
        else:
            cur = conn.execute(
                "INSERT INTO dictionary (term, pattern, replacement, scope, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (term, pattern, replacement, scope, notes, now),
            )
            return {"id": cur.lastrowid, "term": term, "action": "added"}


def remove_term(db_path: str | Path, term_id: int) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM dictionary WHERE id=?", (term_id,))
        return cur.rowcount


def set_enabled(db_path: str | Path, term_id: int, enabled: bool) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute("UPDATE dictionary SET enabled=? WHERE id=?", (1 if enabled else 0, term_id))
        return cur.rowcount


def list_all(db_path: str | Path, scope: Optional[str] = None) -> list[dict]:
    init_dictionary(db_path)
    sql = "SELECT * FROM dictionary"
    params: list = []
    if scope:
        sql += " WHERE scope=?"
        params.append(scope)
    sql += " ORDER BY scope, term"
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def build_whisper_prompt(db_path: str | Path, scope: str = "global", *, max_chars: int = 224) -> str:
    """Whisper의 initial_prompt로 쓸 문장 생성.

    Whisper initial_prompt는 영어 기준 224 토큰 한도. 한국어는 더 빨리 소진.
    가장 중요한 용어들만 선택해서 한 문장으로.
    """
    init_dictionary(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT term FROM dictionary WHERE enabled=1 AND scope IN ('global', ?) ORDER BY id",
            (scope,),
        ).fetchall()
    if not rows:
        return ""
    terms = [r["term"] for r in rows]
    # 자연스러운 문장으로 (Whisper에게 컨텍스트 제공)
    prompt = "이 회의에서 등장하는 용어: " + ", ".join(terms) + "."
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars - 1] + "."
    return prompt


def apply_replacements(db_path: str | Path, text: str, scope: str = "global") -> str:
    """텍스트에 사전의 후처리 치환 규칙 적용."""
    init_dictionary(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT term, pattern, replacement FROM dictionary WHERE enabled=1 AND pattern IS NOT NULL AND pattern <> '' AND scope IN ('global', ?)",
            (scope,),
        ).fetchall()
    for r in rows:
        repl = r["replacement"] or r["term"]
        try:
            text = re.sub(r["pattern"], repl, text)
        except re.error:
            continue  # 잘못된 패턴은 스킵
    return text


def apply_to_segments(db_path: str | Path, segments: list[dict], scope: str = "global") -> tuple[list[dict], int]:
    """발화 리스트의 텍스트에 치환 적용. (수정된 segments, 변경된 발화 수) 반환."""
    out = []
    changed = 0
    for seg in segments:
        original = seg.get("text", "")
        new_text = apply_replacements(db_path, original, scope=scope)
        if new_text != original:
            changed += 1
        out.append({**seg, "text": new_text})
    return out, changed


def import_csv(db_path: str | Path, csv_path: str | Path, *, scope: str = "global") -> int:
    """CSV 일괄 등록.

    포맷: term,pattern,replacement,notes (헤더 필수)
    예:
        term,pattern,replacement,notes
        산업안전,산업안정,산업안전,자주 틀림
        이민재,(?:이민자|이민제),이민재,
    """
    init_dictionary(db_path)
    n = 0
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("term") or "").strip()
            if not term:
                continue
            pattern = (row.get("pattern") or "").strip() or None
            replacement = (row.get("replacement") or "").strip() or None
            notes = (row.get("notes") or "").strip() or None
            add_term(db_path, term, pattern=pattern, replacement=replacement, scope=scope, notes=notes)
            n += 1
    return n
