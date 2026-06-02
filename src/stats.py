"""회의 통계 — 화자별 발언 시간/횟수, 시간대 분포 등."""
from __future__ import annotations

from collections import Counter, defaultdict


def per_speaker_stats(utterances: list[dict]) -> list[dict]:
    """화자별 통계.

    반환: [{speaker, count, total_sec, avg_sec, ratio_pct}, ...] (발언 시간 내림차순)
    """
    if not utterances:
        return []
    counts: Counter[str] = Counter()
    totals: defaultdict[str, float] = defaultdict(float)
    for u in utterances:
        sp = u.get("speaker", "?")
        dur = float(u.get("end", u.get("end_sec", 0))) - float(u.get("start", u.get("start_sec", 0)))
        if dur < 0:
            dur = 0
        counts[sp] += 1
        totals[sp] += dur

    grand_total = sum(totals.values()) or 1.0
    out = []
    for sp, n in counts.items():
        sec = totals[sp]
        out.append({
            "speaker": sp,
            "count": n,
            "total_sec": round(sec, 1),
            "avg_sec": round(sec / n, 1) if n else 0.0,
            "ratio_pct": round(sec * 100 / grand_total, 1),
        })
    out.sort(key=lambda x: -x["total_sec"])
    return out


def time_distribution(utterances: list[dict], chunk_sec: float = 600.0) -> list[dict]:
    """시간 구간(기본 10분)별 발화 통계.

    반환: [{chunk_start, chunk_end, count, total_sec, top_speaker, top_speaker_count}]
    """
    if not utterances:
        return []
    max_end = max(float(u.get("end", u.get("end_sec", 0))) for u in utterances)
    bins: dict[int, list[dict]] = defaultdict(list)
    for u in utterances:
        start = float(u.get("start", u.get("start_sec", 0)))
        bin_id = int(start // chunk_sec)
        bins[bin_id].append(u)

    out = []
    for bin_id in sorted(bins):
        chunk_start = bin_id * chunk_sec
        chunk_end = chunk_start + chunk_sec
        utts = bins[bin_id]
        sp_count = Counter(u.get("speaker", "?") for u in utts)
        top_sp, top_n = sp_count.most_common(1)[0]
        out.append({
            "chunk_start": chunk_start,
            "chunk_end": min(chunk_end, max_end),
            "count": len(utts),
            "total_sec": round(sum(
                float(u.get("end", u.get("end_sec", 0))) - float(u.get("start", u.get("start_sec", 0)))
                for u in utts), 1),
            "top_speaker": top_sp,
            "top_speaker_count": top_n,
        })
    return out


def format_duration(sec: float) -> str:
    if sec < 60:
        return f"{sec:.0f}초"
    m, s = divmod(int(sec), 60)
    if m < 60:
        return f"{m}분 {s}초"
    h, m = divmod(m, 60)
    return f"{h}시간 {m}분"


def format_speaker_table(stats: list[dict]) -> str:
    """콘솔 출력용 표."""
    lines = []
    lines.append(f"\n{'화자':<20} {'발언 횟수':>8} {'총 발언 시간':>12} {'평균 발언':>10} {'비율':>6}")
    lines.append("-" * 65)
    for s in stats:
        lines.append(
            f"{s['speaker']:<20} {s['count']:>8} {format_duration(s['total_sec']):>12} "
            f"{format_duration(s['avg_sec']):>10} {s['ratio_pct']:>5}%"
        )
    return "\n".join(lines)
