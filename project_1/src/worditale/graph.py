"""라우팅(조건부 엣지) + StateGraph 조립.

워크플로우 3패턴: 프롬프트 체이닝(검증 게이트) + Orchestrator-Workers + 병렬(Send).
"""
from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from worditale import nodes
from worditale.config import CHARACTER_SHEET_DEFAULT, HERO_DEFAULT, MAX_RETRIES, TODDLER_MAX_AGE
from worditale.llm import llm_provider
from worditale.state import StoryState


# ── 조건부 엣지 ① : 단어 검사 결과 분기 ──────────────────────
def route_after_check(state: StoryState) -> Literal["reject_input", "plan_story"]:
    return "plan_story" if state["word_check"]["ok"] else "reject_input"


# ── 조건부 엣지 ② : 오케스트레이터 → 페이지 워커 병렬 팬아웃 ─
def fanout_page_workers(state: StoryState) -> list[Send]:
    """브리프를 페이지 워커들에게 Send로 병렬 배분.
    사용자 입력(나이)에 따라 워커 종류(영아용/표준)를 선택하고,
    각 워커에 전체 줄거리 + 자기 브리프 + 앞뒤 장면 요약을 함께 전달한다."""
    briefs = state["page_briefs"]
    worker = (
        "write_page_toddler"
        if state.get("child_age", 4) <= TODDLER_MAX_AGE
        else "write_page_standard"
    )
    # (데모, mock 전용) 첫 시도에 마지막 단어를 빼서 검증→재작성 루프 시연
    drop = None
    if not llm_provider() and state.get("demo_fail_first") and state.get("retry_count", 0) == 0:
        drop = state["target_words"][-1]

    sends = []
    for i, brief in enumerate(briefs):
        sends.append(Send(worker, {
            "brief": brief,
            "prev_scene": briefs[i - 1]["scene"] if i > 0 else None,
            "next_scene": briefs[i + 1]["scene"] if i + 1 < len(briefs) else None,
            "story_plan": state.get("story_plan", ""),
            "hero": state.get("hero", HERO_DEFAULT),
            "demo_drop_word": drop,
        }))
    return sends


# ── 조건부 엣지 ③ : 검증 결과에 따라 워커 재팬아웃 or 마무리 ─
def route_after_validation(state: StoryState) -> list[Send] | Literal["finalize"]:
    if state.get("issues") and state.get("retry_count", 0) <= MAX_RETRIES:
        return fanout_page_workers(state)   # 재작성 루프: 워커들을 다시 병렬 실행
    return "finalize"


# ── 팬아웃 엣지: finalize → 페이지별 삽화 프롬프트 병렬 생성 ─
def fanout_illustrations(state: StoryState) -> list[Send]:
    theme = state.get("theme", "숲속 모험")
    sheet = state.get("character_sheet", CHARACTER_SHEET_DEFAULT)
    return [
        Send("gen_illust_prompt", {"page": p, "theme": theme, "character_sheet": sheet})
        for p in state["pages"]
    ]


# ── 그래프 조립 ──────────────────────────────────────────────
builder = StateGraph(StoryState)
builder.add_node("check_words", nodes.check_words_node)
builder.add_node("reject_input", nodes.reject_input)
builder.add_node("plan_story", nodes.plan_story)
builder.add_node("write_page_toddler", nodes.write_page_toddler)
builder.add_node("write_page_standard", nodes.write_page_standard)
builder.add_node("validate_story", nodes.validate_story)
builder.add_node("finalize", nodes.finalize)
builder.add_node("gen_illust_prompt", nodes.gen_illust_prompt)
builder.add_node("save_storybook", nodes.save_storybook_node)

builder.add_edge(START, "check_words")
builder.add_conditional_edges("check_words", route_after_check)
builder.add_edge("reject_input", END)
builder.add_conditional_edges(
    "plan_story", fanout_page_workers, ["write_page_toddler", "write_page_standard"]
)
builder.add_edge("write_page_toddler", "validate_story")
builder.add_edge("write_page_standard", "validate_story")
builder.add_conditional_edges(
    "validate_story", route_after_validation,
    ["write_page_toddler", "write_page_standard", "finalize"],
)
builder.add_conditional_edges("finalize", fanout_illustrations, ["gen_illust_prompt"])
builder.add_edge("gen_illust_prompt", "save_storybook")
builder.add_edge("save_storybook", END)

# 메모리: thread_id별로 상태(learned_words 등)를 보존하는 체크포인터
graph = builder.compile(checkpointer=MemorySaver())
