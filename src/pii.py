"""민감 정보 (PII) 자동 마스킹.

회의 중 의도치 않게 노출되는 개인정보를 자동 가림 처리.

지원 패턴 (한국):
- 주민등록번호
- 휴대폰 번호
- 일반 전화번호 (지역번호 포함)
- 이메일 주소
- 신용카드 번호
- 계좌번호 (일부 은행 형식)

레벨:
- "off"     : 마스킹 안 함
- "partial" : 일부만 가림 (901234-1****567)
- "full"    : 카테고리 라벨로 대체 ([주민번호])
"""
from __future__ import annotations

import os
import re
from typing import Optional


# ── 패턴 정의 ────────────────────────────────────────────────────

# 한국어 환경에서 \b는 한글-숫자 경계가 word 경계가 아니라 동작이 모호함.
# (?<!\d) ... (?!\d) 로 "앞뒤에 숫자만 없으면 OK" 형태가 더 안전.

# 주민등록번호: 6자리-7자리 (성별 자리 1~4)
RRN_PATTERN = re.compile(r"(?<!\d)(\d{6})[-]?([1-4]\d{6})(?!\d)")

# 휴대폰: 010-xxxx-xxxx, 011/016/017/018/019-xxx-xxxx
MOBILE_PATTERN = re.compile(r"(?<!\d)(01[016-9])[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)")

# 일반 전화: 02-xxx(x)-xxxx, 0xx-xxx(x)-xxxx, 1588-xxxx 등
PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:"
    r"0[2-6][0-9]?[-.\s]?\d{3,4}[-.\s]?\d{4}"   # 지역번호 4그룹 (02-1234-5678 등)
    r"|1[5-9]\d{2}[-.\s]?\d{4}"                  # 1588-1234 등 8자리 대표번호
    r")(?!\d)"
)

# 이메일 (영문 단어 경계는 \b OK)
EMAIL_PATTERN = re.compile(
    r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"
)

# 신용카드 (4-4-4-4 16자리)
CARD_PATTERN = re.compile(
    r"(?<!\d)(\d{4})[-.\s]?(\d{4})[-.\s]?(\d{4})[-.\s]?(\d{4})(?!\d)"
)

# 계좌번호 (3~6 + 2~4 + 4~7 형식의 흔한 패턴)
ACCOUNT_PATTERN = re.compile(
    r"(?<!\d)(\d{3,6})[-](\d{2,4})[-](\d{4,7})(?!\d)"
)


def _mask_rrn(m: re.Match, level: str) -> str:
    if level == "full":
        return "[주민번호]"
    # partial: 901234-1****567
    a, b = m.group(1), m.group(2)
    return f"{a}-{b[0]}****{b[-2:]}"


def _mask_mobile(m: re.Match, level: str) -> str:
    if level == "full":
        return "[휴대폰]"
    a, b, c = m.group(1), m.group(2), m.group(3)
    middle = "*" * len(b)
    return f"{a}-{middle}-{c[-2:].rjust(4, '*')}"


def _mask_phone(m: re.Match, level: str) -> str:
    if level == "full":
        return "[전화번호]"
    s = m.group(0)
    if len(s) <= 4:
        return "*" * len(s)
    body = s[:-4]
    tail = s[-4:]
    return re.sub(r"\d", "*", body) + tail


def _mask_email(m: re.Match, level: str) -> str:
    if level == "full":
        return "[이메일]"
    local, domain = m.group(1), m.group(2)
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def _mask_card(m: re.Match, level: str) -> str:
    # 카드 패턴은 카운트가 적어 신중히. 16자리 연속 숫자만 매칭.
    if level == "full":
        return "[카드번호]"
    a, b, c, d = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"{a}-****-****-{d}"


def _mask_account(m: re.Match, level: str) -> str:
    if level == "full":
        return "[계좌번호]"
    a, b, c = m.group(1), m.group(2), m.group(3)
    return f"{a}-{'*' * len(b)}-{c[:2]}{'*' * (len(c) - 2)}"


def mask_text(text: str, level: Optional[str] = None) -> str:
    """텍스트에 PII 마스킹 적용. level이 'off'이거나 빈 값이면 원본 반환."""
    if not text:
        return text
    if level is None:
        level = os.getenv("PII_MASK_LEVEL", "off").lower().strip()
    if level not in ("partial", "full"):
        return text

    # 순서 중요: 카드(16자리)가 먼저, 그 다음 주민번호(13자리),
    # 그 다음 휴대폰/전화/계좌, 마지막 이메일
    text = CARD_PATTERN.sub(lambda m: _mask_card(m, level), text)
    text = RRN_PATTERN.sub(lambda m: _mask_rrn(m, level), text)
    text = MOBILE_PATTERN.sub(lambda m: _mask_mobile(m, level), text)
    text = PHONE_PATTERN.sub(lambda m: _mask_phone(m, level), text)
    text = ACCOUNT_PATTERN.sub(lambda m: _mask_account(m, level), text)
    text = EMAIL_PATTERN.sub(lambda m: _mask_email(m, level), text)
    return text


def mask_segments(segments: list[dict], level: Optional[str] = None) -> tuple[list[dict], int]:
    """발화 리스트에 마스킹 적용. (수정된 segments, 변경된 발화 수)."""
    if level is None:
        level = os.getenv("PII_MASK_LEVEL", "off").lower().strip()
    if level not in ("partial", "full"):
        return segments, 0

    out = []
    changed = 0
    for seg in segments:
        original = seg.get("text", "")
        new_text = mask_text(original, level)
        if new_text != original:
            changed += 1
        out.append({**seg, "text": new_text})
    return out, changed


def active_level() -> str:
    """현재 PII_MASK_LEVEL 값 (off/partial/full)."""
    return os.getenv("PII_MASK_LEVEL", "off").lower().strip()


def is_enabled() -> bool:
    return active_level() in ("partial", "full")
