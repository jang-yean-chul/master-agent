"""순수 헬퍼 함수 단위 테스트 — 조사 선택, 단어 배치, 페이지 수, 이름 추출."""
from __future__ import annotations

from worditale.config import MAX_PAGES, MIN_PAGES, hero_name
from worditale.nodes import _object_particle, _page_count, _word_buckets


class TestObjectParticle:
    def test_final_consonant_takes_eul(self):
        assert _object_particle("호박") == "을"

    def test_no_final_consonant_takes_reul(self):
        assert _object_particle("사과") == "를"

    def test_non_hangul_defaults_to_reul(self):
        assert _object_particle("apple") == "를"


class TestWordBuckets:
    def test_round_robin_when_more_words_than_buckets(self):
        buckets = _word_buckets(["a", "b", "c", "d", "e"], 3)
        assert buckets == [["a", "d"], ["b", "e"], ["c"]]
        assert sum(len(b) for b in buckets) == 5  # 단어 유실 없음

    def test_one_word_per_bucket(self):
        assert _word_buckets(["a", "b"], 2) == [["a"], ["b"]]


class TestPageCount:
    def test_min_words_gives_words_plus_intro(self):
        # 단어 5개 → 본문 5p + 도입 1p = 6p
        assert _page_count(["a"] * 5) == 6

    def test_capped_at_max_pages(self):
        assert _page_count(["a"] * 10) == MAX_PAGES

    def test_never_below_min_pages(self):
        assert _page_count(["a"] * 2) >= MIN_PAGES


class TestHeroName:
    def test_extracts_last_token(self):
        assert hero_name("아기 토끼 토토") == "토토"

    def test_single_word(self):
        assert hero_name("뽀뽀") == "뽀뽀"

    def test_empty_string(self):
        assert hero_name("") == ""
