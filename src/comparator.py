"""회의 비교 분석.

기능:
1. compare_two(): 두 회의 메타/화자/키워드 비교
2. timeline_stats(): 기간별 회의 통계 (월별 회의수/평균 길이/평균 발화)
3. keyword_trend(): 특정 키워드의 시간별 등장 빈도 추이
4. top_keywords(): 회의에서 가장 자주 등장하는 한국어 명사 추정
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from . import storage


# 한국어 흔한 조사/어미/불용어 — 키워드 분석 시 제외
KO_STOPWORDS = {
    # 1글자 (대부분 단독으로 의미 없음)
    "그", "이", "저", "것", "수", "등", "내", "더", "또", "잘", "왜", "곧", "다",
    "좀", "참", "막", "꼭", "안", "못", "왜", "뭐", "누", "거", "건", "뿐",
    # 인사/추임새
    "네", "예", "어", "음", "아", "오", "헐", "와", "엥",
    # 동사 활용 흔한 어간 (실제 키워드 아니지만 빈도 높음)
    "있는", "있다", "있습니다", "있어", "있고", "있을", "있어요",
    "없는", "없다", "없습니다", "없어",
    "하는", "하고", "하지", "하면", "하기", "한다", "할", "함",
    "되는", "되어", "되고", "되면", "된다",
    "같은", "같이", "같다",
    "그런", "그래서", "그러나", "그리고", "그러면", "그것", "그거",
    "이런", "이거", "이게", "이렇게",
    "정말", "진짜", "아주", "매우", "조금", "약간", "거의", "많이", "별로",
    "다시", "이제", "지금", "오늘", "내일", "어제",
    "통해", "위해", "대해", "대한", "통한", "위한",
    "수가", "수도", "수는", "것이", "것은", "것을", "것도",
    "어떻게", "어떤", "무엇", "어디", "언제",
    # 회의 일반어 (도메인 분석에 노이즈)
    "회의", "말씀", "부분", "내용", "이야기", "얘기", "생각",
    # 1인칭/대명사 활용형
    "우리", "우리가", "우리는", "우리도", "우리를", "우리에게", "우리의", "우리들", "우리들이",
    "저희", "저희가", "저희는", "저희도", "저희들", "저희들이", "저희를",
    "제가", "저는", "저도", "저를", "저의",
    "본인", "본인이", "본인의",
    # 흔한 부사/연결어
    "아까", "이미", "이제", "이번", "이번에", "이번에는",
    "보니", "보니까", "보면", "보는", "본",
    "해서", "해도", "해야", "해야지", "하니까", "하면서", "하기에", "하기로", "하기에는",
    "가지", "가지고", "가지는", "가지면", "가지를",
    "정도", "관련", "경우", "측면", "차원",
    "그래도", "그러니까", "그러므로", "그러기에", "그러면서",
    # 어미 활용 (~겠습니다, ~있도록 등)
    "있도록", "있는데", "있고요", "있구요", "있으면", "있어서", "있어요",
    "없고", "없어", "없습니다", "없는데",
    "하겠습니다", "하겠다", "할게요", "할까요", "한다고", "하는데", "하기는", "하니까",
    "되면서", "되었습니다", "됩니다", "되는데", "되어야", "되어서",
    "같아요", "같습니다", "같아서",
    "드립니다", "드리고", "드릴", "드린", "드리면",
    "주세요", "주시기", "주시면",
    "한번", "두번", "여러", "다른", "이런", "저런", "어느", "여기", "거기", "저기",
    "처음", "마지막",
}


def _korean_words(text: str, *, min_len: int = 2, max_len: int = 12) -> list[str]:
    """한국어 단어(2~12글자) 정규식 추출 (kiwipiepy 미설치 시 폴백)."""
    return re.findall(rf"[가-힣]{{{min_len},{max_len}}}", text)


# kiwipiepy 싱글톤 캐시 (모델 로드 비용 절감)
_KIWI = None
_KIWI_TRIED = False


def _get_kiwi():
    """Kiwi 인스턴스 1회만 초기화. 설치 안 됐으면 None."""
    global _KIWI, _KIWI_TRIED
    if _KIWI_TRIED:
        return _KIWI
    _KIWI_TRIED = True
    try:
        from kiwipiepy import Kiwi
        _KIWI = Kiwi()
        # 첫 호출 워밍업
        _KIWI.tokenize("워밍업")
    except ImportError:
        _KIWI = None
    return _KIWI


# Kiwi 태그:
#   NNG: 일반명사, NNP: 고유명사, SL: 외국어, SN: 숫자
# 분석 대상으로 삼는 태그
_NOUN_TAGS = {"NNG", "NNP", "SL"}


def _extract_nouns_kiwi(kiwi, text: str, *, min_len: int = 2) -> list[str]:
    """Kiwi로 명사 추출 + 인접 명사 결합 (복합명사 보존).

    예: "산업/안전/감독관" 3개 토큰 → "산업안전감독관" 한 단어로.
    """
    tokens = kiwi.tokenize(text)
    out: list[str] = []
    buf: list[str] = []
    for t in tokens:
        if t.tag in _NOUN_TAGS and len(t.form) >= 1:
            buf.append(t.form)
        else:
            if buf:
                # 단독 1글자는 의미 작은 경우 많아 제외
                merged = "".join(buf)
                if len(merged) >= min_len:
                    out.append(merged)
                buf = []
    if buf:
        merged = "".join(buf)
        if len(merged) >= min_len:
            out.append(merged)
    return out


def top_keywords(
    texts: list[str],
    *,
    top_n: int = 30,
    min_count: int = 2,
    exclude: Optional[set[str]] = None,
    method: str = "auto",
) -> list[tuple[str, int]]:
    """텍스트 모음에서 한국어 키워드 빈도 추출.

    method:
        "auto"  - kiwipiepy 있으면 형태소 분석, 없으면 정규식
        "kiwi"  - kiwipiepy 강제 (없으면 ImportError)
        "regex" - 정규식 기반
    """
    stopwords = KO_STOPWORDS | (exclude or set())

    use_kiwi = False
    kiwi = None
    if method == "kiwi":
        from kiwipiepy import Kiwi  # 명시적 실패
        kiwi = _get_kiwi()
        if kiwi is None:
            raise ImportError("kiwipiepy 로드 실패")
        use_kiwi = True
    elif method == "auto":
        kiwi = _get_kiwi()
        use_kiwi = kiwi is not None

    counter: Counter[str] = Counter()
    for text in texts:
        if use_kiwi:
            words = _extract_nouns_kiwi(kiwi, text or "")
        else:
            words = _korean_words(text or "")
        for w in words:
            if w in stopwords:
                continue
            counter[w] += 1
    return [(w, n) for w, n in counter.most_common(top_n) if n >= min_count]


def get_extraction_method() -> str:
    """현재 사용 중인 키워드 추출 방식 (doctor.py 등에서 표시용)."""
    return "kiwipiepy (형태소 분석)" if _get_kiwi() is not None else "정규식 (kiwipiepy 미설치)"


def compare_two(db_path, id_a: int, id_b: int) -> dict:
    """두 회의 직접 비교.

    반환:
        {
            "meetings": {a, b} - 각각의 메타
            "meta_diff": {duration, speaker_count, utterance_count}
            "speakers": {only_in_a, only_in_b, common}
            "keywords": {
                "only_a": [(word, count)],
                "only_b": [(word, count)],
                "shared": [(word, count_a, count_b)],
            }
        }
    """
    a = storage.get_meeting(db_path, id_a)
    b = storage.get_meeting(db_path, id_b)
    if not a or not b:
        raise ValueError(f"meeting not found: a={a is not None}, b={b is not None}")

    ma, mb = a["meeting"], b["meeting"]
    ua, ub = a["utterances"], b["utterances"]

    speakers_a = {u["speaker"] for u in ua}
    speakers_b = {u["speaker"] for u in ub}

    texts_a = [u["text"] for u in ua]
    texts_b = [u["text"] for u in ub]
    kw_a = dict(top_keywords(texts_a, top_n=50, min_count=2))
    kw_b = dict(top_keywords(texts_b, top_n=50, min_count=2))

    only_a = [(w, kw_a[w]) for w in sorted(kw_a.keys() - kw_b.keys(), key=lambda x: -kw_a[x])][:20]
    only_b = [(w, kw_b[w]) for w in sorted(kw_b.keys() - kw_a.keys(), key=lambda x: -kw_b[x])][:20]
    shared_keys = kw_a.keys() & kw_b.keys()
    shared = sorted(
        [(w, kw_a[w], kw_b[w]) for w in shared_keys],
        key=lambda x: -(x[1] + x[2]),
    )[:20]

    return {
        "meetings": {"a": ma, "b": mb},
        "meta_diff": {
            "duration_sec_a": ma["duration_sec"],
            "duration_sec_b": mb["duration_sec"],
            "speaker_count_a": ma["speaker_count"],
            "speaker_count_b": mb["speaker_count"],
            "utterance_count_a": len(ua),
            "utterance_count_b": len(ub),
        },
        "speakers": {
            "only_in_a": sorted(speakers_a - speakers_b),
            "only_in_b": sorted(speakers_b - speakers_a),
            "common": sorted(speakers_a & speakers_b),
        },
        "keywords": {
            "only_a": only_a,
            "only_b": only_b,
            "shared": shared,
        },
    }


def timeline_stats(
    db_path, *, since: Optional[str] = None, until: Optional[str] = None
) -> list[dict]:
    """월별 회의 통계.

    반환: [{month: "2026-03", count, total_sec, avg_sec, total_utterances}, ...]
    """
    sql = "SELECT created_at, duration_sec FROM meetings"
    where = []
    params: list = []
    if since:
        where.append("created_at >= ?"); params.append(since)
    if until:
        where.append("created_at <= ?"); params.append(until)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at"

    bins: defaultdict[str, dict] = defaultdict(lambda: {"count": 0, "total_sec": 0.0})
    utt_counts: defaultdict[str, int] = defaultdict(int)
    meeting_ids_by_month: defaultdict[str, list[int]] = defaultdict(list)

    with storage.connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        for r in rows:
            ts = (r["created_at"] or "")[:7] or "(미상)"
            bins[ts]["count"] += 1
            bins[ts]["total_sec"] += float(r["duration_sec"] or 0)
        # 월별 발화 수 집계
        for r in conn.execute(
            "SELECT strftime('%Y-%m', m.created_at) AS month, COUNT(u.id) AS n "
            "FROM meetings m LEFT JOIN utterances u ON u.meeting_id = m.id "
            "GROUP BY month"
        ).fetchall():
            utt_counts[r["month"] or "(미상)"] = r["n"]

    out = []
    for month in sorted(bins.keys()):
        b = bins[month]
        out.append({
            "month": month,
            "count": b["count"],
            "total_sec": round(b["total_sec"], 1),
            "avg_sec": round(b["total_sec"] / b["count"], 1) if b["count"] else 0.0,
            "utterance_count": utt_counts.get(month, 0),
        })
    return out


def keyword_trend(
    db_path, keyword: str, *, since: Optional[str] = None, until: Optional[str] = None
) -> list[dict]:
    """특정 키워드의 월별 등장 빈도.

    반환: [{month, meeting_count, occurrence_count}, ...]
    """
    pat = re.escape(keyword)
    sql = (
        "SELECT strftime('%Y-%m', m.created_at) AS month, m.id, u.text "
        "FROM meetings m JOIN utterances u ON u.meeting_id = m.id "
    )
    where = []
    params: list = []
    if since:
        where.append("m.created_at >= ?"); params.append(since)
    if until:
        where.append("m.created_at <= ?"); params.append(until)
    if where:
        sql += " WHERE " + " AND ".join(where)

    by_month_meetings: defaultdict[str, set[int]] = defaultdict(set)
    by_month_occ: defaultdict[str, int] = defaultdict(int)
    regex = re.compile(pat)

    with storage.connect(db_path) as conn:
        for r in conn.execute(sql, params).fetchall():
            month = r["month"] or "(미상)"
            n = len(regex.findall(r["text"] or ""))
            if n > 0:
                by_month_meetings[month].add(r["id"])
                by_month_occ[month] += n

    months = sorted(by_month_meetings.keys() | by_month_occ.keys())
    return [{
        "month": m,
        "meeting_count": len(by_month_meetings[m]),
        "occurrence_count": by_month_occ[m],
    } for m in months]


def speaker_trend(
    db_path, speaker: str, *, since: Optional[str] = None, until: Optional[str] = None
) -> list[dict]:
    """특정 화자의 월별 발언 통계."""
    sql = (
        "SELECT strftime('%Y-%m', m.created_at) AS month, "
        "       COUNT(u.id) AS utterance_count, "
        "       SUM(u.end_sec - u.start_sec) AS total_sec, "
        "       COUNT(DISTINCT m.id) AS meeting_count "
        "FROM meetings m JOIN utterances u ON u.meeting_id = m.id "
        "WHERE u.speaker = ? "
    )
    params: list = [speaker]
    if since:
        sql += " AND m.created_at >= ? "
        params.append(since)
    if until:
        sql += " AND m.created_at <= ? "
        params.append(until)
    sql += " GROUP BY month ORDER BY month"
    with storage.connect(db_path) as conn:
        return [{
            "month": r["month"] or "(미상)",
            "meeting_count": r["meeting_count"],
            "utterance_count": r["utterance_count"],
            "total_sec": round(float(r["total_sec"] or 0), 1),
        } for r in conn.execute(sql, params).fetchall()]
