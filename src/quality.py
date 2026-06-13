"""Transcript quality heuristics for safe meeting-note publishing.

The goal is not to prove that a transcript is correct. We only flag signals
that often mean the transcript or speaker labels are unsafe to publish as-is.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from statistics import mean


SEVERITY_ORDER = {"ok": 0, "warning": 1, "danger": 2}


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    message: str
    detail: str = ""


@dataclass(frozen=True)
class QualityReport:
    severity: str
    issues: tuple[QualityIssue, ...]
    metrics: dict[str, float | int]

    @property
    def ok(self) -> bool:
        return self.severity == "ok"

    @property
    def should_block_upload(self) -> bool:
        return self.severity == "danger"


def _severity_label(severity: str) -> str:
    return {
        "ok": "정상",
        "warning": "주의",
        "danger": "낮음",
    }.get(severity, severity)


def _norm_text(text: str) -> str:
    text = re.sub(r"\s+", "", text or "").lower()
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text_repetition_ratio(texts: list[str]) -> tuple[float, float]:
    normalized = [_norm_text(t) for t in texts]
    normalized = [t for t in normalized if len(t) >= 8]
    if len(normalized) < 6:
        return 0.0, 0.0

    duplicate_ratio = (len(normalized) - len(set(normalized))) / len(normalized)

    near_repeats = 0
    comparisons = 0
    for prev, cur in zip(normalized, normalized[1:]):
        comparisons += 1
        if prev == cur:
            near_repeats += 1
            continue
        short, long = sorted((prev, cur), key=len)
        if len(short) >= 12 and short in long:
            near_repeats += 1
            continue
        if SequenceMatcher(None, prev, cur).ratio() >= 0.86:
            near_repeats += 1
    near_repeat_ratio = near_repeats / max(comparisons, 1)
    return duplicate_ratio, near_repeat_ratio


def _clean_segments(segments: list[dict]) -> list[dict]:
    clean: list[dict] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = _float_or_none(seg.get("start", seg.get("start_sec"))) or 0.0
        end = _float_or_none(seg.get("end", seg.get("end_sec")))
        if end is None:
            end = start
        clean.append({**seg, "text": text, "start": start, "end": end})
    return clean


def _report_severity(issues: list[QualityIssue]) -> str:
    if not issues:
        return "ok"
    return max(issues, key=lambda issue: SEVERITY_ORDER.get(issue.severity, 0)).severity


def analyze_segments(segments: list[dict], *, duration_sec: float) -> QualityReport:
    clean = _clean_segments(segments)
    duration_sec = max(0.0, float(duration_sec or 0.0))
    duration_min = max(duration_sec / 60.0, 1e-6)

    utterance_count = len(clean)
    speech_sec = sum(max(0.0, float(s["end"]) - float(s["start"])) for s in clean)
    speech_ratio = speech_sec / max(duration_sec, 1e-6) if duration_sec else 0.0
    texts = [str(s["text"]) for s in clean]
    total_chars = sum(len(t) for t in texts)
    chars_per_min = total_chars / duration_min
    speakers = [str(s.get("speaker") or "") for s in clean]
    speaker_count = len({s for s in speakers if s})

    speaker_durations: dict[str, float] = {}
    for seg in clean:
        speaker = str(seg.get("speaker") or "")
        speaker_durations[speaker] = speaker_durations.get(speaker, 0.0) + max(
            0.0, float(seg["end"]) - float(seg["start"])
        )
    dominant_speaker_ratio = (
        max(speaker_durations.values()) / max(speech_sec, 1e-6)
        if speaker_durations and speech_sec > 0
        else 0.0
    )
    duplicate_ratio, near_repeat_ratio = _text_repetition_ratio(texts)

    avg_logprobs = [
        v for v in (_float_or_none(s.get("avg_logprob")) for s in clean)
        if v is not None
    ]
    no_speech_probs = [
        v for v in (_float_or_none(s.get("no_speech_prob")) for s in clean)
        if v is not None
    ]
    compression_ratios = [
        v for v in (_float_or_none(s.get("compression_ratio")) for s in clean)
        if v is not None
    ]
    low_logprob_ratio = (
        sum(1 for v in avg_logprobs if v < -1.1) / len(avg_logprobs)
        if avg_logprobs
        else 0.0
    )
    high_no_speech_ratio = (
        sum(1 for v in no_speech_probs if v >= 0.65) / len(no_speech_probs)
        if no_speech_probs
        else 0.0
    )
    high_compression_ratio = (
        sum(1 for v in compression_ratios if v >= 2.4) / len(compression_ratios)
        if compression_ratios
        else 0.0
    )

    metrics: dict[str, float | int] = {
        "duration_sec": round(duration_sec, 1),
        "utterance_count": utterance_count,
        "speaker_count": speaker_count,
        "speech_ratio": round(speech_ratio, 3),
        "chars_per_min": round(chars_per_min, 1),
        "duplicate_ratio": round(duplicate_ratio, 3),
        "near_repeat_ratio": round(near_repeat_ratio, 3),
        "dominant_speaker_ratio": round(dominant_speaker_ratio, 3),
        "low_logprob_ratio": round(low_logprob_ratio, 3),
        "high_no_speech_ratio": round(high_no_speech_ratio, 3),
        "high_compression_ratio": round(high_compression_ratio, 3),
    }

    issues: list[QualityIssue] = []
    if utterance_count == 0:
        issues.append(QualityIssue(
            "no_speech",
            "danger",
            "인식된 발화가 없습니다.",
            "오디오가 비어 있거나, VAD/음질 문제로 말소리를 모두 놓쳤을 수 있습니다.",
        ))
        return QualityReport("danger", tuple(issues), metrics)

    if duration_sec >= 120 and utterance_count <= 2:
        issues.append(QualityIssue(
            "too_few_utterances",
            "danger",
            "긴 파일인데 발화가 거의 감지되지 않았습니다.",
            f"길이 {duration_sec:.0f}초, 발화 {utterance_count}건",
        ))
    elif duration_sec >= 180 and utterance_count / duration_min < 1.0:
        issues.append(QualityIssue(
            "sparse_utterances",
            "warning",
            "발화 밀도가 낮아 일부 말이 누락됐을 수 있습니다.",
            f"분당 발화 {utterance_count / duration_min:.1f}건",
        ))

    if duration_sec >= 180 and speech_ratio < 0.08:
        issues.append(QualityIssue(
            "low_speech_ratio",
            "danger",
            "오디오 길이에 비해 인식된 말소리 구간이 너무 적습니다.",
            f"음성 비율 {speech_ratio:.1%}",
        ))
    elif duration_sec >= 180 and speech_ratio < 0.15:
        issues.append(QualityIssue(
            "low_speech_ratio",
            "warning",
            "오디오 길이에 비해 인식된 말소리 구간이 적습니다.",
            f"음성 비율 {speech_ratio:.1%}",
        ))

    if duration_sec >= 180 and chars_per_min < 40:
        issues.append(QualityIssue(
            "low_text_amount",
            "danger",
            "긴 파일인데 인식된 글자 수가 너무 적습니다.",
            f"분당 {chars_per_min:.0f}자",
        ))
    elif duration_sec >= 180 and chars_per_min < 90:
        issues.append(QualityIssue(
            "low_text_amount",
            "warning",
            "인식된 텍스트 양이 적어 회의 내용이 빠졌을 수 있습니다.",
            f"분당 {chars_per_min:.0f}자",
        ))

    if duration_sec >= 300 and utterance_count >= 15 and speaker_count <= 1:
        issues.append(QualityIssue(
            "single_speaker_long",
            "warning",
            "긴 녹음인데 화자가 1명으로만 인식되었습니다.",
            "실제 다인원 회의라면 화자 분리가 실패했을 가능성이 큽니다.",
        ))
    elif (
        duration_sec >= 300
        and utterance_count >= 20
        and speaker_count >= 2
        and dominant_speaker_ratio >= 0.93
    ):
        issues.append(QualityIssue(
            "dominant_speaker",
            "warning",
            "대부분의 발화가 한 화자에 몰렸습니다.",
            f"최대 화자 비중 {dominant_speaker_ratio:.1%}",
        ))

    if duplicate_ratio >= 0.30 or near_repeat_ratio >= 0.22:
        issues.append(QualityIssue(
            "repeated_text",
            "danger",
            "같거나 매우 비슷한 문장이 반복 인식되었습니다.",
            "잡음, 음악, 박수, 울림을 말소리로 잘못 인식했을 수 있습니다.",
        ))
    elif duplicate_ratio >= 0.16 or near_repeat_ratio >= 0.12:
        issues.append(QualityIssue(
            "repeated_text",
            "warning",
            "반복 문장이 많아 STT 환각 가능성이 있습니다.",
            f"중복 {duplicate_ratio:.1%}, 인접 반복 {near_repeat_ratio:.1%}",
        ))

    if avg_logprobs and (low_logprob_ratio >= 0.35 or mean(avg_logprobs) < -1.15):
        issues.append(QualityIssue(
            "low_asr_confidence",
            "danger",
            "Whisper 신뢰도 지표가 낮습니다.",
            f"낮은 logprob 비율 {low_logprob_ratio:.1%}",
        ))
    elif avg_logprobs and (low_logprob_ratio >= 0.20 or mean(avg_logprobs) < -0.95):
        issues.append(QualityIssue(
            "low_asr_confidence",
            "warning",
            "Whisper 신뢰도 지표가 좋지 않습니다.",
            f"낮은 logprob 비율 {low_logprob_ratio:.1%}",
        ))

    if no_speech_probs and high_no_speech_ratio >= 0.30:
        issues.append(QualityIssue(
            "high_no_speech_prob",
            "warning",
            "무음/비음성으로 의심되는 구간이 많이 텍스트화되었습니다.",
            f"높은 no_speech_prob 비율 {high_no_speech_ratio:.1%}",
        ))

    if compression_ratios and high_compression_ratio >= 0.20:
        issues.append(QualityIssue(
            "high_compression",
            "warning",
            "반복성 높은 Whisper 출력이 감지되었습니다.",
            f"높은 compression_ratio 비율 {high_compression_ratio:.1%}",
        ))

    if _report_severity(issues) != "danger":
        # 화자 분포 경고(단일화자/한 명 편중)는 1인 강의·인터뷰·보고 녹음처럼 정상일 수
        # 있으므로 danger 승격 산정에서 제외한다. 실제로 본문이 망가졌다는 강한 신호
        # (반복 환각·무음·신뢰도 붕괴·텍스트량 부족)만 2개 이상 겹칠 때 danger로 올린다.
        soft_codes = {"single_speaker_long", "dominant_speaker"}
        strong_warnings = sum(
            1 for issue in issues
            if issue.severity == "warning" and issue.code not in soft_codes
        )
        if strong_warnings >= 2:
            issues.append(QualityIssue(
                "combined_quality_risk",
                "danger",
                "품질 위험 신호가 여러 개 겹쳤습니다.",
                "자동 업로드보다는 원문 확인 후 게시하는 것이 안전합니다.",
            ))

    return QualityReport(_report_severity(issues), tuple(issues), metrics)


def format_console_lines(report: QualityReport) -> list[str]:
    if report.ok:
        return ["[info] 자동 품질 점검: 통과"]
    lines = [f"[warn] 자동 품질 점검: {_severity_label(report.severity)}"]
    for issue in report.issues[:6]:
        detail = f" ({issue.detail})" if issue.detail else ""
        lines.append(f"    - {issue.message}{detail}")
    if len(report.issues) > 6:
        lines.append(f"    - 추가 경고 {len(report.issues) - 6}건")
    return lines


def render_markdown_notice(report: QualityReport) -> str:
    if report.ok:
        return ""
    issue_lines = "\n".join(
        f"- {issue.message}" + (f" ({issue.detail})" if issue.detail else "")
        for issue in report.issues[:6]
    )
    return (
        "## 품질 경고\n"
        f"- 자동 인식 품질: **{_severity_label(report.severity)}**\n"
        "- 이 회의록은 자동 초안이며, 원문 확인 전에는 그대로 확정하지 않는 것이 안전합니다.\n"
        f"{issue_lines}\n\n"
        "---"
    )


def prepend_quality_notice(summary_md: str, report: QualityReport) -> str:
    notice = render_markdown_notice(report)
    if not notice:
        return summary_md
    return f"{notice}\n\n{summary_md.lstrip()}"
