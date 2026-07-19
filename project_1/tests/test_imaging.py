"""imaging 테스트 — 삽화 아래 글귀 띠 합성."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from worditale.imaging import caption_image, find_font


def _png(w: int = 200, h: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "red").save(buf, "PNG")
    return buf.getvalue()


class TestCaptionImage:
    def test_band_added_below_image(self):
        if not find_font():
            pytest.skip("한글 폰트 없는 환경 — 합성은 원본 반환으로 폴백")
        out = caption_image(_png(), "토토는 사과를 만나 활짝 웃었어요.")
        img = Image.open(io.BytesIO(out))
        assert img.width == 200          # 폭 유지
        assert img.height > 100          # 아래로 띠가 늘어남 (그림을 가리지 않음)

    def test_long_text_wraps_to_taller_band(self):
        if not find_font():
            pytest.skip("한글 폰트 없는 환경")
        short = Image.open(io.BytesIO(caption_image(_png(), "짧은 글")))
        long = Image.open(io.BytesIO(caption_image(
            _png(), "아주 아주 긴 문장이 들어가면 여러 줄로 접혀서 띠가 더 높아져야 해요 " * 3
        )))
        assert long.height > short.height

    def test_empty_text_returns_original(self):
        data = _png()
        assert caption_image(data, "   ") == data

    def test_broken_image_returns_original(self):
        data = b"not a png"
        assert caption_image(data, "글귀") == data
