"""툴 테스트 — check_words 1차 규칙 필터, save_storybook 파일 저장."""
from __future__ import annotations

from worditale.tools import check_words, save_storybook

VALID_WORDS = ["사과", "나비", "구름", "바람", "노래"]


class TestCheckWords:
    def test_valid_words_pass(self):
        result = check_words.invoke({"words": VALID_WORDS})
        assert result == {"ok": True, "problems": []}

    def test_too_few_words(self):
        result = check_words.invoke({"words": ["사과", "나비"]})
        assert not result["ok"]
        assert "개수" in result["problems"][0]

    def test_too_many_words(self):
        result = check_words.invoke({"words": [f"단어{i}" for i in range(11)]})
        assert not result["ok"]

    def test_banned_word_rejected(self):
        result = check_words.invoke({"words": VALID_WORDS[:4] + ["칼"]})
        assert not result["ok"]
        assert any("부적합" in p for p in result["problems"])

    def test_non_hangul_rejected(self):
        result = check_words.invoke({"words": VALID_WORDS[:4] + ["apple"]})
        assert not result["ok"]
        assert any("한글" in p for p in result["problems"])

    def test_too_long_word_rejected(self):
        result = check_words.invoke({"words": VALID_WORDS[:4] + ["아주아주긴단어"]})
        assert not result["ok"]

    def test_multiple_problems_all_reported(self):
        result = check_words.invoke({"words": ["칼", "gun"]})  # 개수 + 금지어 + 비한글
        assert len(result["problems"]) == 3


class TestSaveStorybook:
    PAGES = [{"page": 2, "text": "둘째 장"}, {"page": 1, "text": "첫째 장"}]
    PROMPTS = [{"page": 1, "prompt": "a rabbit"}]

    def test_saves_markdown_with_pages_in_order(self, isolated_output):
        path = save_storybook.invoke(
            {"title": "숲속 이야기", "pages": self.PAGES, "illust_prompts": self.PROMPTS}
        )
        content = (isolated_output / "output" / "숲속 이야기.md").read_text(encoding="utf-8")
        assert path.endswith("숲속 이야기.md")
        assert content.index("첫째 장") < content.index("둘째 장")  # 페이지 번호순 정렬
        assert "삽화 프롬프트: a rabbit" in content

    def test_unsafe_title_chars_stripped(self, isolated_output):
        path = save_storybook.invoke(
            {"title": "동화: <모험>?", "pages": self.PAGES, "illust_prompts": []}
        )
        assert path.endswith("동화 모험.md")

    def test_all_invalid_title_falls_back(self, isolated_output):
        path = save_storybook.invoke(
            {"title": "???", "pages": self.PAGES, "illust_prompts": []}
        )
        assert path.endswith("storybook.md")

    def test_image_embedded_as_relative_path(self, isolated_output):
        img = isolated_output / "output" / "images" / "숲속 이야기" / "p1.png"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"png")
        prompts = [{"page": 1, "prompt": "a rabbit", "image_path": str(img)}]
        save_storybook.invoke(
            {"title": "숲속 이야기", "pages": self.PAGES, "illust_prompts": prompts}
        )
        content = (isolated_output / "output" / "숲속 이야기.md").read_text(encoding="utf-8")
        assert "![1페이지 삽화](images/숲속 이야기/p1.png)" in content  # output/ 기준 상대 경로
        assert "삽화 프롬프트: a rabbit" in content
