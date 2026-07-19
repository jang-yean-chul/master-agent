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
    plan_illustrations,
    plan_story,
    polish_story,
    validate_story,
    write_story_standard,
    write_story_toddler,
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
        assert result["needs_replan"] is False
        assert result["character_sheet"] == CHARACTER_SHEET_DEFAULT

    def test_replan_preserves_retry_count_and_clears_flag(self):
        """서사 문제로 되돌아온 재계획은 retry_count를 보존해 루프 상한을 지킨다."""
        state = _base_state(needs_replan=True, issues=["서사 문제: 인과 없음"], retry_count=2)
        result = plan_story(state)
        assert result["retry_count"] == 2
        assert result["needs_replan"] is False

    def test_stale_flag_without_issues_is_fresh_run(self):
        """issues가 비었으면 needs_replan이 남아 있어도 새 동화로 취급(리셋)."""
        result = plan_story(_base_state(needs_replan=True, issues=[], retry_count=3))
        assert result["retry_count"] == 0

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


# ── 이야기 전체 집필 (한 호흡 작성) ──────────────────────────
def _writer_state(age: int = 4, **over) -> dict:
    """plan_story(mock)의 브리프를 포함한 집필용 state."""
    state = _base_state(child_age=age, hero="아기 토끼 토토")
    state.update(plan_story(state))
    state.update(over)
    return state


class TestStoryWriters:
    def test_standard_covers_all_words_and_matches_briefs(self):
        state = _writer_state()
        pages = write_story_standard(state)["pages"]
        assert len(pages) == len(state["page_briefs"])
        full = " ".join(p["text"] for p in pages)
        for w in WORDS:
            assert w in full

    def test_pages_numbered_in_order(self):
        pages = write_story_standard(_writer_state())["pages"]
        assert [p["page"] for p in pages] == list(range(1, len(pages) + 1))

    def test_standard_last_page_has_closing(self):
        pages = write_story_standard(_writer_state())["pages"]
        assert "잠들었답니다" in pages[-1]["text"]

    def test_toddler_last_page_has_closing(self):
        pages = write_story_toddler(_writer_state(age=2))["pages"]
        assert "코~ 잘 자요" in pages[-1]["text"]

    def test_demo_fail_first_drops_last_word_only_on_first_try(self):
        state = _writer_state(demo_fail_first=True, retry_count=0)
        full = " ".join(p["text"] for p in write_story_standard(state)["pages"])
        assert WORDS[-1] not in full   # 첫 시도: 일부러 누락 (재작성 루프 시연)

        state["retry_count"] = 1
        full = " ".join(p["text"] for p in write_story_standard(state)["pages"])
        assert WORDS[-1] in full       # 재작성: 복구

    def test_llm_bad_page_count_falls_back_to_mock(self, monkeypatch):
        """LLM이 페이지 수를 어긴 출력을 주면 mock 로직으로 폴백."""
        state = _writer_state()  # 브리프는 mock plan으로 먼저 확보
        bad = json.dumps({"pages": [{"page": 1, "text": "한 쪽짜리"}]})
        _fake_llm(monkeypatch, bad)
        pages = write_story_standard(state)["pages"]
        assert len(pages) == len(state["page_briefs"])


# ── polish_story (이음새 다듬기 — 안전망 검사) ───────────────
class TestPolishStory:
    def _pages(self):
        return [
            {"page": 1, "text": "토토가 일어났어요."},
            {"page": 2, "text": "사과를 먹고 나비를 만났어요."},
            {"page": 3, "text": "구름이 떠 있어요."},
            {"page": 4, "text": "바람이 불어요."},
            {"page": 5, "text": "노래를 부르며 잠들었어요."},
        ]

    def test_mock_mode_is_noop(self):
        assert polish_story({"pages": self._pages(), "target_words": WORDS}) == {}

    def test_skips_when_issues_remain(self, monkeypatch):
        _fake_llm(monkeypatch, "호출되면 안 됨")
        result = polish_story({"pages": self._pages(), "target_words": WORDS,
                               "issues": ["문제"]})
        assert result == {}

    def test_rejects_polish_that_drops_a_word(self, monkeypatch):
        bad = json.dumps({"pages": [{"page": p["page"], "text": "말랑말랑한 문장"}
                                    for p in self._pages()]})
        _fake_llm(monkeypatch, bad)
        result = polish_story({"pages": self._pages(), "target_words": WORDS, "issues": []})
        assert result == {}  # 단어가 사라진 다듬기는 버리고 원본 유지

    def test_accepts_valid_polish(self, monkeypatch):
        polished = self._pages()
        polished[2]["text"] = "그런데 하늘엔 구름이 두둥실 떠 있었어요."
        _fake_llm(monkeypatch, json.dumps({"pages": polished}))
        result = polish_story({"pages": self._pages(), "target_words": WORDS, "issues": []})
        assert result["pages"][2]["text"].startswith("그런데")


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
        assert update == {"issues": [], "needs_replan": False}

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

    def test_rule_issue_does_not_trigger_replan(self):
        """단어 누락 같은 규칙 문제는 재집필로 충분 — 재계획 아님."""
        update = validate_story({"pages": self._valid_pages(),
                                 "target_words": WORDS + ["기차"], "retry_count": 0})
        assert update["needs_replan"] is False


class TestValidateNarrative:
    """서사 품질 LLM 판정 — 연결어만 있고 인과 없는 '장면 나열' 검출 (2026-07-20)."""

    def _valid_pages(self):
        return _pages([
            "토토가 일어났어요.",
            "사과를 먹고 나비를 만났어요.",
            "구름이 두둥실 떠 있어요.",
            "바람이 살랑 불어요.",
            "노래를 부르며 잠들었어요.",
        ])

    def test_narrative_failure_reported_with_replan(self, monkeypatch):
        safe = json.dumps({"safe": True})
        disjointed = json.dumps({"ok": False, "reason": "3쪽이 앞 장면과 무관하게 시작됨"})
        _fake_llm(monkeypatch, safe, disjointed)
        update = validate_story({"pages": self._valid_pages(),
                                 "target_words": WORDS, "retry_count": 0})
        assert any("서사 문제" in i for i in update["issues"])
        assert update["needs_replan"] is True
        assert update["retry_count"] == 1

    def test_coherent_story_passes_both_judges(self, monkeypatch):
        _fake_llm(monkeypatch, json.dumps({"safe": True}), json.dumps({"ok": True}))
        update = validate_story({"pages": self._valid_pages(), "target_words": WORDS})
        assert update == {"issues": [], "needs_replan": False}

    def test_judge_crash_treated_as_pass(self, monkeypatch):
        _fake_llm(monkeypatch, json.dumps({"safe": True}), "JSON 아님!!!")
        update = validate_story({"pages": self._valid_pages(), "target_words": WORDS})
        assert update["issues"] == []


class TestRouteAfterValidation:
    """검증 결과 라우팅 — 서사 문제는 설계(plan)부터, 규칙 문제는 재집필로."""

    def test_narrative_issue_routes_to_replan(self):
        from worditale.graph import route_after_validation
        state = {"issues": ["서사 문제: 인과 없음"], "needs_replan": True,
                 "retry_count": 1, "child_age": 4}
        assert route_after_validation(state) == "plan_story"

    def test_rule_issue_routes_to_rewrite(self):
        from worditale.graph import route_after_validation
        state = {"issues": ["누락된 학습 단어: 기차"], "needs_replan": False,
                 "retry_count": 1, "child_age": 4}
        assert route_after_validation(state) == "write_story_standard"

    def test_exhausted_retries_proceed_to_polish(self):
        from worditale.config import MAX_RETRIES
        from worditale.graph import route_after_validation
        state = {"issues": ["서사 문제: 인과 없음"], "needs_replan": True,
                 "retry_count": MAX_RETRIES + 1, "child_age": 4}
        assert route_after_validation(state) == "polish_story"


# ── finalize · gen_illust_prompt ─────────────────────────────
class TestFinalize:
    def test_ok_accumulates_learned_words(self):
        update = finalize({"issues": [], "target_words": WORDS})
        assert update == {"status": "ok", "needs_replan": False, "learned_words": WORDS}

    def test_failure_does_not_record_words(self):
        update = finalize({"issues": ["문제"], "target_words": WORDS})
        assert update == {"status": "failed_validation", "needs_replan": False}


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

    def test_mock_mode_never_generates_image(self):
        """mock 모드(키 없음)에선 illust_quality를 켜도 이미지 없이 프롬프트만."""
        result = gen_illust_prompt({
            "page": {"page": 1, "text": "토토가 일어났어요."},
            "theme": "숲속 모험",
            "illust_quality": "low",
        })
        entry = result["illust_prompts"][0]
        assert "prompt" in entry
        assert "image_path" not in entry

    def test_planned_scene_takes_priority(self):
        """연출 계획(illust_scene)이 있으면 페이지 단위 장면 생성 대신 그것을 쓴다."""
        result = gen_illust_prompt({
            "page": {"page": 2, "text": "사과를 만났어요."},
            "theme": "숲속 모험",
            "illust_scene": "Toto finds an apple in the same sunny meadow as before",
            "character_sheet": "the same main character on every page: a fox",
        })
        prompt = result["illust_prompts"][0]["prompt"]
        assert "the same sunny meadow" in prompt   # 계획된 장면 사용
        assert prompt.startswith("the same main character")  # 시트로 시작 (기록 재현성)


class TestGenIllustImageFailure:
    """이미지 생성 실패 처리 — 참조 없이 1회 재시도, 최종 실패는 error로 표시.
    (2026-07-20: 조용한 삼킴 때문에 특정 쪽 그림이 이유 없이 빠지던 문제)"""

    def _payload(self):
        return {
            "page": {"page": 3, "text": "토토가 길을 건너요."},
            "theme": "도심 속 모험",
            "illust_quality": "low",
            "character_sheet": "the same main character on every page: a fox",
            "illust_scene": "Toto crosses the street safely",
        }

    def test_failure_after_retry_records_error(self, monkeypatch):
        monkeypatch.setattr(nodes, "image_provider", lambda: "openai")
        calls = {"n": 0}

        def boom(prompt, quality="low"):
            calls["n"] += 1
            raise RuntimeError("moderation_blocked")

        monkeypatch.setattr(nodes, "generate_image", boom)
        entry = gen_illust_prompt(self._payload())["illust_prompts"][0]
        assert calls["n"] == 2              # 1차 + 참조 없는 재시도 = 총 2회
        assert "image_path" not in entry
        assert "error" in entry             # 실패를 숨기지 않고 기록

    def test_retry_succeeds_after_transient_failure(self, monkeypatch, tmp_path):
        from worditale import tools
        monkeypatch.setattr(nodes, "image_provider", lambda: "openai")
        monkeypatch.setattr(tools, "PROJECT_ROOT", tmp_path)
        calls = {"n": 0}

        def flaky(prompt, quality="low"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return b"fake-png-bytes"

        monkeypatch.setattr(nodes, "generate_image", flaky)
        entry = gen_illust_prompt(self._payload())["illust_prompts"][0]
        assert entry.get("image_path")
        assert "error" not in entry


# ── plan_illustrations (삽화 연출 계획 — 그림 이음새) ────────
class TestPlanIllustrations:
    PAGES = [{"page": 1, "text": "토토가 일어났어요."},
             {"page": 2, "text": "사과를 만났어요."}]

    def test_mock_fallback_one_scene_per_page(self):
        result = plan_illustrations({"pages": self.PAGES, "theme": "숲속 모험"})
        assert [s["page"] for s in result["illust_scenes"]] == [1, 2]
        assert result["setting_sheet"]  # 배경 기준 묘사도 함께

    def test_llm_scene_count_mismatch_falls_back(self, monkeypatch):
        bad = json.dumps({"setting": "a forest", "scenes": [{"page": 1, "scene": "only one"}]})
        _fake_llm(monkeypatch, bad)
        result = plan_illustrations({"pages": self.PAGES, "theme": "숲속 모험"})
        assert len(result["illust_scenes"]) == len(self.PAGES)  # 폴백

    def test_llm_valid_plan_used(self, monkeypatch):
        good = json.dumps({
            "setting": "a sunny meadow by a small stream",
            "scenes": [{"page": 1, "scene": "Toto wakes up in the meadow"},
                       {"page": 2, "scene": "Toto finds an apple in the same meadow"}],
        })
        _fake_llm(monkeypatch, good)
        result = plan_illustrations({"pages": self.PAGES, "theme": "숲속 모험"})
        assert result["setting_sheet"] == "a sunny meadow by a small stream"
        assert "same meadow" in result["illust_scenes"][1]["scene"]
