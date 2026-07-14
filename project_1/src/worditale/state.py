"""그래프 State 정의 — TypedDict + 리듀서."""
from __future__ import annotations

from typing import Annotated, TypedDict


class Page(TypedDict):
    page: int
    text: str


class IllustPrompt(TypedDict):
    page: int
    prompt: str


class PageBrief(TypedDict):
    """오케스트레이터(plan_story)가 페이지 워커에게 내리는 작업 지시서."""
    page: int
    role: str          # 도입 / 전개 / 마무리 — 서사에서 이 페이지의 역할
    scene: str         # 이 페이지에서 벌어지는 일 (한 줄)
    words: list[str]   # 이 페이지가 반드시 사용할 학습 단어


def _extend_or_reset(old: list | None, new) -> list:
    """illust_prompts 리듀서: Send 병렬 결과는 이어붙이고, None이면 초기화(새 동화 시작)."""
    if new is None:
        return []
    return (old or []) + list(new)


def _merge_pages(old: list | None, new) -> list:
    """pages 리듀서: 워커 병렬 결과를 페이지 번호로 병합.
    재작성 루프에서 같은 페이지는 덮어쓰고, None이면 초기화(새 동화 시작)."""
    if new is None:
        return []
    merged = {p["page"]: p for p in (old or [])}
    for p in new:
        merged[p["page"]] = p
    return [merged[k] for k in sorted(merged)]


def _union_words(old: list | None, new: list | None) -> list:
    """learned_words 리듀서: 배운 단어를 중복 없이 누적 (thread 메모리)."""
    return sorted(set(old or []) | set(new or []))


class StoryState(TypedDict, total=False):
    # 입력
    target_words: list[str]     # 가르칠 단어 5~10개
    child_age: int              # 아이 나이 → 작문 스타일 분기 (사용자 입력 조건부 엣지)
    theme: str                  # 동화 테마
    hero: str                   # 주인공 설정 (예: "아기 토끼 토토") — 캐릭터 일관성의 기준
    demo_fail_first: bool       # (데모용) 첫 시도에 단어 하나를 일부러 누락시켜 루프 시연
    # 중간 산출물
    word_check: dict            # check_words 툴 결과 {"ok": bool, "problems": [...]}
    story_plan: str             # plan_story 결과: 줄거리 개요
    character_sheet: str        # 주인공 외형 묘사(영어 1문장) — 모든 삽화 프롬프트에 동일 삽입
    page_briefs: list[PageBrief]  # 오케스트레이터의 페이지별 작업 지시서
    pages: Annotated[list[Page], _merge_pages]  # 페이지 워커 병렬 결과 (번호로 병합)
    illust_prompts: Annotated[list[IllustPrompt], _extend_or_reset]  # Send 병렬 결과
    # 검증/제어
    issues: list[str]           # validate_story가 찾은 문제 목록
    retry_count: int            # 재작성 횟수
    status: str                 # "ok" | "failed_validation" | "rejected"
    saved_path: str             # save_storybook 툴이 저장한 파일 경로
    # 메모리 (thread별 누적)
    learned_words: Annotated[list[str], _union_words]  # 지금까지 배운 단어
