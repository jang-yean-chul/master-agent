"""State 리듀서 테스트 — Send 병렬 결과 병합/누적/초기화 규칙."""
from __future__ import annotations

from worditale.state import _extend_or_reset, _merge_pages, _union_words


class TestMergePages:
    def test_parallel_results_sorted_by_page(self):
        merged = _merge_pages(
            [{"page": 2, "text": "b"}],
            [{"page": 1, "text": "a"}, {"page": 3, "text": "c"}],
        )
        assert [p["page"] for p in merged] == [1, 2, 3]

    def test_rewrite_overwrites_same_page(self):
        merged = _merge_pages(
            [{"page": 1, "text": "old"}],
            [{"page": 1, "text": "new"}],
        )
        assert merged == [{"page": 1, "text": "new"}]

    def test_none_resets_for_new_story(self):
        assert _merge_pages([{"page": 1, "text": "a"}], None) == []


class TestExtendOrReset:
    def test_appends(self):
        assert _extend_or_reset([1], [2, 3]) == [1, 2, 3]

    def test_none_old_starts_fresh(self):
        assert _extend_or_reset(None, [1]) == [1]

    def test_none_new_resets(self):
        assert _extend_or_reset([1, 2], None) == []


class TestUnionWords:
    def test_dedupes_and_sorts(self):
        assert _union_words(["나비", "구름"], ["구름", "바람"]) == ["구름", "나비", "바람"]

    def test_handles_none(self):
        assert _union_words(None, None) == []
