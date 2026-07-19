"""라우팅(조건부 엣지) + StateGraph 조립.

워크플로우 패턴: 프롬프트 체이닝(기획 → 집필 → 검증 게이트 → 다듬기)
+ 병렬 처리(Send — 기준 캐릭터를 참조한 페이지별 삽화 생성 ×N).
검증 게이트는 문제 종류에 따라 두 갈래로 되돌린다:
규칙/안전 문제 → 재집필, 서사(인과·기승전결) 문제 → 설계(plan)부터 재계획.

집필은 한 호흡(1콜)으로 전체를 쓴다 — 페이지를 병렬 워커로 쪼개면
문장 이음새가 끊기기 때문 (2026-07-18 구조 변경). 병렬성은 삽화가 담당.
"""
from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from worditale import nodes
from worditale.config import CHARACTER_SHEET_DEFAULT, MAX_RETRIES, THEME_DEFAULT, TODDLER_MAX_AGE
from worditale.state import StoryState


# ── 조건부 엣지 ① : 단어 검사 결과 분기 ──────────────────────
def route_after_check(state: StoryState) -> Literal["reject_input", "plan_story"]:
    return "plan_story" if state["word_check"]["ok"] else "reject_input"


# ── 조건부 엣지 ② : 나이(사용자 입력)에 따라 집필 스타일 분기 ─
def route_by_age(state: StoryState) -> Literal["write_story_toddler", "write_story_standard"]:
    return (
        "write_story_toddler"
        if state.get("child_age", 4) <= TODDLER_MAX_AGE
        else "write_story_standard"
    )


# ── 조건부 엣지 ③ : 검증 결과 — 재계획 / 재집필 / 다듬기 ────
def route_after_validation(
    state: StoryState,
) -> Literal["plan_story", "write_story_toddler", "write_story_standard", "polish_story"]:
    if state.get("issues") and state.get("retry_count", 0) <= MAX_RETRIES:
        if state.get("needs_replan"):
            return "plan_story"      # 서사 문제: 브리프(설계)가 원인 — 설계부터 다시
        return route_by_age(state)   # 규칙/안전 문제: 피드백과 함께 전체 재집필
    return "polish_story"


# ── 팬아웃 엣지: 기준 이미지들 → 페이지별 삽화 병렬 생성 ─────
def fanout_illustrations(state: StoryState) -> list[Send]:
    theme = state.get("theme", THEME_DEFAULT)
    sheet = state.get("character_sheet", CHARACTER_SHEET_DEFAULT)
    quality = state.get("illust_quality", "off")
    caption = state.get("illust_caption", True)
    scene_by_page = {s["page"]: s["scene"] for s in state.get("illust_scenes", [])}
    return [
        Send("gen_illust_prompt", {
            "page": p, "theme": theme, "character_sheet": sheet,
            "illust_quality": quality, "illust_caption": caption,
            "character_ref": state.get("character_ref"),
            "setting_ref": state.get("setting_ref"),
            "illust_scene": scene_by_page.get(p["page"]),
        })
        for p in state["pages"]
    ]


# ── 그래프 조립 ──────────────────────────────────────────────
builder = StateGraph(StoryState)
builder.add_node("check_words", nodes.check_words_node)
builder.add_node("reject_input", nodes.reject_input)
builder.add_node("plan_story", nodes.plan_story)
builder.add_node("write_story_toddler", nodes.write_story_toddler)
builder.add_node("write_story_standard", nodes.write_story_standard)
builder.add_node("validate_story", nodes.validate_story)
builder.add_node("polish_story", nodes.polish_story)
builder.add_node("finalize", nodes.finalize)
builder.add_node("plan_illustrations", nodes.plan_illustrations)
builder.add_node("gen_character_ref", nodes.gen_character_ref)
builder.add_node("gen_illust_prompt", nodes.gen_illust_prompt)
builder.add_node("save_storybook", nodes.save_storybook_node)

builder.add_edge(START, "check_words")
builder.add_conditional_edges("check_words", route_after_check)
builder.add_edge("reject_input", END)
builder.add_conditional_edges("plan_story", route_by_age)
builder.add_edge("write_story_toddler", "validate_story")
builder.add_edge("write_story_standard", "validate_story")
builder.add_conditional_edges(
    "validate_story", route_after_validation,
    ["plan_story", "write_story_toddler", "write_story_standard", "polish_story"],
)
builder.add_edge("polish_story", "finalize")
builder.add_edge("finalize", "plan_illustrations")
builder.add_edge("plan_illustrations", "gen_character_ref")
builder.add_conditional_edges("gen_character_ref", fanout_illustrations, ["gen_illust_prompt"])
builder.add_edge("gen_illust_prompt", "save_storybook")
builder.add_edge("save_storybook", END)

# 메모리: thread_id별로 상태(learned_words 등)를 보존하는 체크포인터
graph = builder.compile(checkpointer=MemorySaver())
