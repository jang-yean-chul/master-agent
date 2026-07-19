"""삽화 이미지에 페이지 텍스트를 합성 — 한 장짜리 그림책 페이지로 완성.

이미지 모델에게 한글을 그리게 하면 글자가 깨지기 쉬우므로,
생성된 삽화 아래에 크림색 띠를 덧붙여 Pillow로 직접 글귀를 그린다
(그림은 가리지 않고, 글씨는 항상 정확하게).
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# DESIGN.md "머리맡의 그림책" 팔레트와 통일
BAND_COLOR = "#FFF9F0"   # 크림 띠 배경
TEXT_COLOR = "#33261D"   # 따뜻한 잉크

# 한글 폰트 후보 (앞에서부터 탐색):
#   저장소 동봉(assets/fonts) → Windows 맑은 고딕 → Linux 나눔 계열
#   Streamlit Cloud에서는 packages.txt의 fonts-nanum이 나눔 폰트를 설치한다.
_FONT_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "assets" / "fonts" / "NanumSquareRoundB.ttf",
    Path("C:/Windows/Fonts/malgunbd.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
]


def find_font() -> str | None:
    """사용 가능한 첫 번째 한글 폰트 경로. 없으면 None(합성 건너뜀)."""
    for p in _FONT_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """측정 기반 단어 단위 줄바꿈."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [text]


def caption_image(data: bytes, text: str, *, font_size: int = 40) -> bytes:
    """삽화 PNG 아래에 크림 띠를 덧붙이고 페이지 글귀를 가운데 정렬로 그린다.

    폰트가 없거나 합성에 실패하면 원본 바이트를 그대로 반환한다
    (글귀 합성 실패가 동화 완성을 막으면 안 됨).
    """
    font_path = find_font()
    if not font_path or not text.strip():
        return data
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        font = ImageFont.truetype(font_path, font_size)
        pad = max(24, img.width // 36)
        draw = ImageDraw.Draw(img)
        lines = _wrap(draw, text.strip(), font, img.width - pad * 2)

        line_h = int(font_size * 1.45)
        band_h = pad * 2 + line_h * len(lines)
        page = Image.new("RGB", (img.width, img.height + band_h), BAND_COLOR)
        page.paste(img, (0, 0))

        d = ImageDraw.Draw(page)
        y = img.height + pad
        for ln in lines:
            w = d.textlength(ln, font=font)
            d.text(((img.width - int(w)) // 2, y), ln, font=font, fill=TEXT_COLOR)
            y += line_h

        out = io.BytesIO()
        page.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return data
