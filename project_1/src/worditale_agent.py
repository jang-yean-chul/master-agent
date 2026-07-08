"""
WordiTale (워디테일) — 유아 단어 학습 동화 생성 에이전트
Step 2: LangGraph 기초 구축

그래프: START → plan_story → write_pages → validate_story
        ├─ (검증 실패, 재시도 가능) → write_pages  [루프]
        └─ (통과 or 재시도 소진)   → finalize → END

LLM 연동: ANTHROPIC_API_KEY 환경변수가 있으면 Claude API 호출,
          없으면 mock(규칙 기반 더미) 로직으로 동작.

실행: python worditale_agent.py
"""
from __future__ import annotations

import json
import os
import re
from typing import Literal, TypedDict

from langgraph.graph import StateGraph, START, END

# ── 비즈니스 규칙 상수 ─────────────────────────────────────────
MIN_WORDS, MAX_WORDS = 5, 10        # 학습 단어 개수
MIN_PAGES, MAX_PAGES = 5, 8         # 동화 페이지 수
MAX_CHARS_PER_PAGE = 100            # 페이지당 최대 글자 수 (유아용 간단 텍스트)
MAX_RETRIES = 2                     # 재작성 루프 상한 (무한 루프 방지)


# ── State 정의 ────────────────────────────────────────────────
class Page(TypedDict):
    page: int
    text: str


class StoryState(TypedDict, total=False):
    # 입력
    target_words: list[str]     # 가르칠 단어 5~10개
    child_age: int              # 아이 나이
    theme: str                  # 동화 테마
    demo_fail_first: bool       # (데모용) 첫 시도에 단어 하나를 일부러 누락시켜 루프 시연
    # 중간 산출물
    story_plan: str             # plan_story 결과: 줄거리 개요
    pages: list[Page]           # write_pages 결과: 페이지별 텍스트
    # 검증/제어
    issues: list[str]           # validate_story가 찾은 문제 목록
    retry_count: int            # 재작성 횟수
    status: str                 # "ok" | "failed_validation"


# ── LLM 호출 (겸용: 실제 API ↔ mock) ─────────────────────────
def _llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _call_claude(prompt: str) -> str:
    """ANTHROPIC_API_KEY가 있을 때만 사용."""
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def _object_particle(word: str) -> str:
    """한국어 목적격 조사 을/를 선택 (mock 문장 자연스럽게)."""
    ch = word[-1]
    if "가" <= ch <= "힣":
        return "을" if (ord(ch) - 0xAC00) % 28 else "를"
    return "를"


# ── 노드 1: 스토리 플래닝 ────────────────────────────────────
def plan_story(state: StoryState) -> dict:
    words = state["target_words"]
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        raise ValueError(f"학습 단어는 {MIN_WORDS}~{MAX_WORDS}개여야 합니다 (현재 {len(words)}개)")

    age, theme = state.get("child_age", 4), state.get("theme", "숲속 모험")

    if _llm_available():
        plan = _call_claude(
            f"{age}세 유아용 동화 줄거리 개요를 5문장 이내로 써줘. "
            f"테마: {theme}. 반드시 이 단어들이 이야기에 등장해야 해: {', '.join(words)}. "
            f"폭력적이거나 무서운 요소 없이 따뜻하게."
        )
    else:  # mock
        plan = (
            f"아기 토끼 '토토'가 {theme}을 떠나요. "
            f"길에서 {', '.join(words)}(을)를 하나씩 만나며 신나는 하루를 보내고, "
            f"저녁에 엄마 품으로 돌아와 포근히 잠들어요."
        )
    return {"story_plan": plan, "retry_count": state.get("retry_count", 0)}


# ── 노드 2: 페이지별 텍스트 생성 ─────────────────────────────
def write_pages(state: StoryState) -> dict:
    words = state["target_words"]
    n_pages = min(MAX_PAGES, max(MIN_PAGES, len(words) + 1))

    if _llm_available():
        raw = _call_claude(
            f"다음 개요로 {n_pages}페이지 유아 동화를 써줘.\n개요: {state['story_plan']}\n"
            f"규칙: 페이지당 1~2문장({MAX_CHARS_PER_PAGE}자 이내), "
            f"이 단어들을 모두 본문에 사용: {', '.join(words)}.\n"
            f'JSON 배열로만 답해: [{{"page": 1, "text": "..."}}, ...]'
        )
        pages: list[Page] = json.loads(re.search(r"\[.*\]", raw, re.S).group())
    else:  # mock: 단어를 2페이지~마지막 페이지에 라운드로빈 배치
        body_pages = n_pages - 1
        buckets: list[list[str]] = [[] for _ in range(body_pages)]
        for i, w in enumerate(words):
            buckets[i % body_pages].append(w)

        pages = [{"page": 1, "text": "아침 해가 뜨자 아기 토끼 토토가 폴짝 일어났어요."}]
        for i, bucket in enumerate(buckets, start=2):
            parts = [f"토토는 {w}{_object_particle(w)} 만나 활짝 웃었어요." for w in bucket]
            pages.append({"page": i, "text": " ".join(parts)})
        pages[-1]["text"] += " 토토는 엄마 품에서 새근새근 잠들었답니다."

        # (데모) 첫 시도에서 마지막 단어를 일부러 빼서 검증→재작성 루프를 시연
        if state.get("demo_fail_first") and state.get("retry_count", 0) == 0:
            missing = words[-1]
            for p in pages:
                p["text"] = p["text"].replace(
                    f"토토는 {missing}{_object_particle(missing)} 만나 활짝 웃었어요.", ""
                ).strip() or "토토가 깡충깡충 뛰어갔어요."

    return {"pages": pages}


# ── 노드 3: 검증 (규칙 기반, LLM 불필요) ─────────────────────
def validate_story(state: StoryState) -> dict:
    pages, words = state["pages"], state["target_words"]
    full_text = " ".join(p["text"] for p in pages)
    issues: list[str] = []

    if not (MIN_PAGES <= len(pages) <= MAX_PAGES):
        issues.append(f"페이지 수 위반: {len(pages)}p (허용 {MIN_PAGES}~{MAX_PAGES}p)")
    missing = [w for w in words if w not in full_text]  # 조사 결합형도 부분일치로 검출
    if missing:
        issues.append(f"누락된 학습 단어: {', '.join(missing)}")
    for p in pages:
        if len(p["text"]) > MAX_CHARS_PER_PAGE:
            issues.append(f"{p['page']}페이지 텍스트 과다: {len(p['text'])}자")

    update: dict = {"issues": issues}
    if issues:
        update["retry_count"] = state.get("retry_count", 0) + 1
    return update


# ── 노드 4: 마무리 ───────────────────────────────────────────
def finalize(state: StoryState) -> dict:
    ok = not state.get("issues")
    return {"status": "ok" if ok else "failed_validation"}


# ── 조건부 엣지: 검증 결과에 따라 분기 ───────────────────────
def route_after_validation(state: StoryState) -> Literal["write_pages", "finalize"]:
    if state.get("issues") and state.get("retry_count", 0) <= MAX_RETRIES:
        return "write_pages"   # 재작성 루프
    return "finalize"


# ── 그래프 조립 ──────────────────────────────────────────────
builder = StateGraph(StoryState)
builder.add_node("plan_story", plan_story)
builder.add_node("write_pages", write_pages)
builder.add_node("validate_story", validate_story)
builder.add_node("finalize", finalize)

builder.add_edge(START, "plan_story")
builder.add_edge("plan_story", "write_pages")
builder.add_edge("write_pages", "validate_story")
builder.add_conditional_edges("validate_story", route_after_validation)
builder.add_edge("finalize", END)

graph = builder.compile()


# ── 데모 실행 ────────────────────────────────────────────────
if __name__ == "__main__":
    mode = "Claude API" if _llm_available() else "mock"
    print(f"=== WordiTale 실행 (LLM 모드: {mode}) ===\n")

    result = graph.invoke({
        "target_words": ["사과", "구름", "나비", "바람", "무지개", "달팽이"],
        "child_age": 4,
        "theme": "숲속 모험",
        "demo_fail_first": True,   # 검증 실패 → 재작성 루프 시연
    })

    print(f"[줄거리] {result['story_plan']}\n")
    for p in result["pages"]:
        print(f"  p{p['page']}. {p['text']}")
    print(f"\n[검증] 재작성 {result['retry_count']}회, 최종 상태: {result['status']}")
    if result.get("issues"):
        print(f"[남은 문제] {result['issues']}")
