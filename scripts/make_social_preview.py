"""GitHub Social Preview 이미지 생성 (1280x640 PNG).

GitHub 권장 크기: 1280x640 (2:1 비율).
링크 공유 시 미리보기로 표시됨.

사용:
    python scripts/make_social_preview.py
    → ./assets/social_preview.png 생성

GitHub 업로드 위치:
    Repository → Settings → 좌측 Options/General → Social preview → Upload an image
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


# 색상 (다크 톤 + 한국어/뱃지용 강조색)
BG_TOP = (24, 28, 36)        # 진한 남색
BG_BOTTOM = (38, 44, 56)
ACCENT = (255, 200, 87)      # 노란 강조
ACCENT_2 = (110, 220, 180)   # 청록
TEXT = (240, 240, 245)
SUBTEXT = (160, 170, 185)
BADGE_BG = (60, 70, 86)
LINE = (70, 80, 96)


def _try_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    """가장 먼저 발견되는 폰트 사용. 한국어 지원 폰트 우선."""
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _font_korean(size: int) -> ImageFont.FreeTypeFont:
    """한국어 포함 폰트 (Windows / Linux 후보)."""
    return _try_font([
        "C:/Windows/Fonts/malgunbd.ttf",   # 맑은 고딕 Bold
        "C:/Windows/Fonts/malgun.ttf",     # 맑은 고딕
        "C:/Windows/Fonts/NanumGothicBold.ttf",
        "C:/Windows/Fonts/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf",
    ], size)


def _font_mono(size: int) -> ImageFont.FreeTypeFont:
    return _try_font([
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ], size)


def make_gradient(w: int, h: int) -> Image.Image:
    """위→아래 그라데이션."""
    img = Image.new("RGB", (w, h), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def draw_badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
                font: ImageFont.FreeTypeFont, color_text=TEXT, color_bg=BADGE_BG,
                padding: tuple[int, int] = (16, 8)) -> int:
    """배지 그리기. 반환: 차지한 너비."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = padding
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    draw.rounded_rectangle([x, y, x + bw, y + bh], radius=bh // 2, fill=color_bg)
    draw.text((x + pad_x - bbox[0], y + pad_y - bbox[1]), text, fill=color_text, font=font)
    return bw


def main() -> int:
    W, H = 1280, 640
    img = make_gradient(W, H)
    draw = ImageDraw.Draw(img)

    # 좌측 강조 띠
    draw.rectangle([(0, 0), (16, H)], fill=ACCENT)

    # 우상단 작은 아이콘 영역 (간단한 점들로 음파 표현)
    cx, cy = W - 180, 110
    for i in range(7):
        h_bar = 10 + abs(((i - 3) * 18))
        c = ACCENT_2 if i % 2 == 0 else ACCENT
        draw.rectangle([cx + i * 22, cy - h_bar // 2, cx + i * 22 + 14, cy + h_bar // 2],
                       fill=c)

    # 제목
    title_font = _font_korean(76)
    subtitle_font = _font_korean(38)
    body_font = _font_korean(28)
    badge_font = _font_korean(22)
    mono_font = _font_mono(24)

    margin = 80
    y = 110

    # 한국어 제목
    draw.text((margin, y), "회의록 자동 기록", fill=TEXT, font=title_font)
    y += 92

    # 영문 부제
    draw.text((margin, y), "Korean Meeting Audio → STT + Diarization + LLM Summary",
              fill=SUBTEXT, font=subtitle_font)
    y += 70

    # 핵심 문장
    draw.text((margin, y),
              "음성 → 화자 분리 → 한국어 요약 → 그누보드5 자동 등록",
              fill=ACCENT, font=body_font)
    y += 50
    draw.text((margin, y),
              "Fully local · No cloud · Free (open source + Ollama)",
              fill=SUBTEXT, font=body_font)
    y += 80

    # 배지들
    badges = [
        ("WhisperX", BADGE_BG),
        ("speechbrain", BADGE_BG),
        ("Ollama (gemma)", BADGE_BG),
        ("SQLite FTS5", BADGE_BG),
        ("Streamlit", BADGE_BG),
        ("Gnuboard5", BADGE_BG),
        ("Python 3.10+", BADGE_BG),
        ("PHP", BADGE_BG),
    ]
    bx, by = margin, y
    for label, bg in badges:
        w = draw_badge(draw, bx, by, label, badge_font, color_bg=bg)
        bx += w + 12
        if bx > W - margin - 200:
            bx = margin
            by += 50
    y = by + 80

    # 구분선
    draw.line([(margin, H - 90), (W - margin, H - 90)], fill=LINE, width=2)

    # 하단: github URL + 라이센스
    draw.text((margin, H - 60),
              "github.com/thisgun/meeting_record",
              fill=TEXT, font=mono_font)
    draw.text((W - margin - 240, H - 60),
              "LGPL-2.1-or-later",
              fill=SUBTEXT, font=mono_font)

    # 저장
    out = Path(__file__).resolve().parent.parent / "assets" / "social_preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    print(f"✓ 생성됨: {out}")
    print(f"  크기: {out.stat().st_size / 1024:.1f} KB ({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
