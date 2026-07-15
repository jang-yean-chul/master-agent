"""노드 단위 테스트 — 오케스트레이터 안전망, 페이지 워커, 검증 게이트, 마무리.

LLM 경로는 nodes.call_llm / nodes.llm_provider를 monkeypatch해서
'LLM이 이상한 출력을 줬을 때' 폴백이 동작하는지까지 검사한다.
"""
from __future__ import annotations

import json

from worditale import nodes
from worditale.config import (
    CHARACTER_SHEET_DEFAULT,
    MAX_CHARS_PER_PAGE,
    MAX_PAGES,
    MIN_PAGES,
)
from worditale.nodes import (
    finalize,
    gen_illust_prompt,
    plan_story,
    validate_story,
    write_page_standard,
    write_page_toddler,
)

WORDS = ["사과", "나비", "구름", "바람", "노래"]


def _base_state(**over) -> dict:
    state = {"target_words": WORDS, "child_age": 4, "theme": "숲속 모험"}
    state.update(over)
    return state


def _fake_llm(monkeypatch, *responses):
    """nodes의 LLM 경로를 켜고, call_llm이 responses를 순서대로 반환하게 한다."""
    replies = iter(responses)
    monkeypatch.setattr(nodes, "llm_provider", lambda: "fake")
    monkeypatch.setattr(nodes, "call_llm", lambda prompt, max_tokens=1500: next(replies))


# ── plan_story (오케스트레이터) ──────────────────────────────
class TestPlanStoryMock:
    def test_briefs_cover_all_words(self):
        result = plan_story(_base_state())
        assigned = [w for b in result["page_briefs"] for w in b["words"]]
        assert sorted(assigned) == sorted(WORDS)

    def test_page_count_in_range_and_intro_has_no_words(self):
        briefs = plan_story(_base_state())["page_briefs"]
        assert MIN_PAGES <= len(briefs) <= MAX_PAGES
        assert briefs[0]["role"] == "도입" and briefs[0]["words"] == []

    def test_resets_previous_run_state(self):
        result = plan_story(_base_state())
        assert result["pages"] is None          # 리듀서가 [] 로 초기화
        assert result["retry_count"] == 0
        assert result["issues"] == []
        assert result["character_sheet"] == CHARACTER_SHEET_DEFAULT

    def test_memory_review_words_appear_in_plan(self):
        result = plan_story(_base_state(learned_words=["기차", "무지개"]))
        assert "기차" in result["story_plan"] and "무지개" in result["story_plan"]

    def test_review_excludes_words_already_in_targets(self):
        result = plan_story(_base_state(learned_words=[WORDS[0]]))
        assert "지난번에 배운" not in result["story_plan"]


class TestPlanStorySafetyNet:
    """LLM이 규격을 벗어난 계획을 내놨을 때의 보정 로직."""

    SHEET = "the same main character on every page: a fox"

    def test_out_of_range_page_count_falls_back_to_rule_briefs(self, monkeypatch):
        bad = json.dumps({
            "plan": "줄거리",
            "pages": [{"page": 1, "role": "도입", "scene": "s", "words": []},
                      {"page": 2, "role": "마무리", "scene": "s", "words": WORDS}],
        })  # 2페이지 — MIN_PAGES 미달
        _fake_llm(monkeypatch, bad, self.SHEET)
        briefs = plan_story(_base_state())["page_briefs"]
        assert MIN_PAGES <= len(briefs) <= MAX_PAGES
        assigned = {w for b in briefs for w in b["words"]}
        assert assigned == set(WORDS)

    def test_missing_words_appended_to_last_page(self, monkeypatch):
        pages = [{"page": i, "role": "전개", "scene": f"장면{i}", "words": []}
                 for i in range(1, 6)]
        pages[1]["words"] = WORDS[:4]  # '노래' 누락
        _fake_llm(monkeypatch, json.dumps({"plan": "줄거리", "pages": pages}), self.SHEET)
        briefs = plan_story(_base_state())["page_briefs"]
        assert "노래" in briefs[-1]["words"]

    def test_llm_page_numbers_normalized(self, monkeypatch):
        pages = [{"page": 99, "role": "전개", "scene": f"장면{i}", "words": [w]}
                 for i, w in enumerate(WORDS, start=1)]
        _fake_llm(monkeypatch, json.dumps({"plan": "줄거리", "pages": pages}), self.SHEET)
        briefs = plan_story(_base_state())["page_briefs"]
        assert [b["page"] for b in briefs] == list(range(1, len(briefs) + 1))


# ── 페이지 워커 ──────────────────────────────────────────────
def _payload(brief, **over) -> dict:
    payload = {"brief": brief, "story_plan": "줄거리", "prev_scene": "앞 장면",
               "next_scene": "뒤 장면", "hero": "아기 토끼 토토"}
    payload.update(over)
    return payload


class TestPageWorkers:
    BRIEF = {"page": 3, "role": "전개", "scene": "사과를 만난다", "words": ["사과", "나비"]}

    def test_standard_includes_assigned_words(self):
        text = write_page_standard(_payload(self.BRIEF))["pages"][0]["text"]
        assert "사과" in text and "나비" in text

    def test_standard_returns_page_number_from_brief(self):
        assert write_page_standard(_payload(self.BRIEF))["pages"][0]["page"] == 3

    def test_standard_last_page_has_closing(self):
        text = write_page_standard(_payload(self.BRIEF, next_scene=None))["pages"][0]["text"]
        assert "잠들었답니다" in text

    def test_toddler_includes_word_and_closing(self):
        text = write_page_toddler(_payload(self.BRIEF, next_scene=None))["pages"][0]["text"]
        assert "사과" in text
        assert "코~ 잘 자요" in text

    def test_demo_drop_word_excluded(self):
        text = write_page_standard(
            _payload(self.BRIEF, demo_drop_word="나비")
        )["pages"][0]["text"]
        assert "나비" not in text and "사과" in text


# ── validate_story (검증 게이트) ─────────────────────────────
def _pages(texts: list[str]) -> list[dict]:
    return [{"page": i, "text": t} for i, t in enumerate(texts, start=1)]


class TestValidateStory:
    def _valid_pages(self):
        # 5페이지 · 단어 5개 모두 포함 (조사 결합형 포함) · 글자 수 준수
        return _pages([
            "토토가 일어났어요.",
            "사과를 먹고 나비를 만났어요.",
            "구름이 두둥실 떠 있어요.",
            "바람이 살랑 불어요.",
            "노래를 부르며 잠들었어요.",
        ])

    def test_valid_story_has_no_issues(self):
        update = validate_story({"pages": self._valid_pages(), "target_words": WORDS})
        assert update == {"issues": []}

    def test_particle_attached_word_counts_as_covered(self):
        """'사과를'처럼 조사가 붙어도 부분일치로 커버 처리되는지."""
        update = validate_story({"pages": self._valid_pages(), "target_words": ["사과"]})
        assert update["issues"] == []

    def test_missing_word_reported_and_retry_incremented(self):
        state = {"pages": self._valid_pages(), "target_words": WORDS + ["기차"],
                 "retry_count": 0}
        update = validate_story(state)
        assert any("기차" in i for i in update["issues"])
        assert update["retry_count"] == 1

    def test_page_count_violation(self):
        update = validate_story({"pages": _pages(["사과 나비 구름 바람 노래"]),
                                 "target_words": WORDS})
        assert any("페이지 수 위반" in i for i in update["issues"])

    def test_overlong_page_reported(self):
        pages = self._valid_pages()
        pages[2]["text"] = "구름 " + "아" * MAX_CHARS_PER_PAGE
        update = validate_story({"pages": pages, "target_words": WORDS})
        assert any("텍스트 과다" in i for i in update["issues"])

    def test_banned_word_in_output_caught(self):
        pages = self._valid_pages()
        pages[3]["text"] = "바람이 불자 유령이 나타났어요."
        update = validate_story({"pages": pages, "target_words": WORDS})
        assert any("부적절 단어" in i for i in update["issues"])

    def test_single_char_banned_words_not_false_positive(self):
        """'칼국수'의 '칼' 같은 1글자 금지어 오탐이 없어야 한다."""
        pages = self._valid_pages()
        pages[1]["text"] = "사과와 나비와 함께 칼국수를 먹었어요."
        update = validate_story({"pages": pages, "target_words": WORDS})
        assert update["issues"] == []


# ── finalize · gen_illust_prompt ─────────────────────────────
class TestFinalize:
    def test_ok_accumulates_learned_words(self):
        update = finalize({"issues": [], "target_words": WORDS})
        assert update == {"status": "ok", "learned_words": WORDS}

    def test_failure_does_not_record_words(self):
        update = finalize({"issues": ["문제"], "target_words": WORDS})
        assert update == {"status": "failed_validation"}


class TestGenIllustPrompt:
    def test_prompt_starts_with_character_sheet(self):
        sheet = "the same main character on every page: a fox"
        result = gen_illust_prompt({
            "page": {"page": 1, "text": "토토가 일어났어요."},
            "theme": "숲속 모험",
            "character_sheet": sheet,
        })
        prompt = result["illust_prompts"][0]["prompt"]
        assert prompt.startswith(sheet)  # 캐릭터 일관성: 모든 페이지 동일 시트로 시작
        assert "숲속 모험" in prompt
