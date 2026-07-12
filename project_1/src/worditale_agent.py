"""
WordiTale (워디테일) — 유아 단어 학습 동화 생성 에이전트
Step 3: 툴 연동 + 사용자 입력 분기 + Send 병렬 + 메모리

그래프:
START → check_words(툴①: 단어 적합성 검사)
  ├─ 부적합 단어 → reject_input → END                    [조건부 엣지 ①]
  └─ 통과 → plan_story
       ├─ child_age ≤ 3 → write_pages_toddler            [조건부 엣지 ②: 사용자 입력(나이) 분기]
       └─ child_age ≥ 4 → write_pages_standard
            → validate_story ↔ (재작성 루프, 최대 2회)     [조건부 엣지 ③]
            → finalize → [Send 병렬] gen_illust_prompt ×N  [페이지별 삽화 프롬프트 팬아웃]
            → save_storybook(툴②: 파일 저장) → END

메모리: MemorySaver 체크포인터 + thread_id(아이별 세션).
        같은 thread_id로 다시 실행하면 learned_words(배운 단어)가 누적되어
        다음 동화 개요에 복습 단어로 반영된다.

LLM 연동: OPENAI_API_KEY → OpenAI, ANTHROPIC_API_KEY → Claude,
          둘 다 없으면 mock(규칙 기반 더미) 로직으로 동작.

실행: python src/worditale_agent.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

# ── 비즈니스 규칙 상수 ─────────────────────────────────────────
MIN_WORDS, MAX_WORDS = 5, 10        # 학습 단어 개수
MIN_PAGES, MAX_PAGES = 5, 8         # 동화 페이지 수
MAX_CHARS_PER_PAGE = 100            # 페이지당 최대 글자 수 (유아용 간단 텍스트)
MAX_RETRIES = 2                     # 재작성 루프 상한 (무한 루프 방지)
TODDLER_MAX_AGE = 3                 # 이 나이 이하면 영아용 작문 스타일

# 유아 동화에 넣을 수 없는 단어 (예시 목록)
BANNED_WORDS = {"칼", "총", "술", "담배", "죽음", "귀신", "피", "지옥"}

# 기본 주인공 — 모든 페이지·삽화에서 동일 캐릭터 유지 (사용자가 바꿀 수 있음)
HERO_DEFAULT = "아기 토끼 토토"
CHARACTER_SHEET_DEFAULT = (
    "the same main character on every page: a cute baby rabbit named Toto "
    "with soft cream fur, round pink cheeks, and a tiny yellow scarf"
)


def _hero_name(hero: str) -> str:
    """주인공 문구에서 부를 이름만 추출 ('아기 토끼 토토' → '토토')."""
    return hero.split()[-1] if hero.split() else hero


# ── State 정의 ────────────────────────────────────────────────
class Page(TypedDict):
    page: int
    text: str


class IllustPrompt(TypedDict):
    page: int
    prompt: str


def _extend_or_reset(old: list | None, new) -> list:
    """illust_prompts 리듀서: Send 병렬 결과는 이어붙이고, None이면 초기화(새 동화 시작)."""
    if new is None:
        return []
    return (old or []) + list(new)


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
    pages: list[Page]           # write_pages_* 결과: 페이지별 텍스트
    illust_prompts: Annotated[list[IllustPrompt], _extend_or_reset]  # Send 병렬 결과
    # 검증/제어
    issues: list[str]           # validate_story가 찾은 문제 목록
    retry_count: int            # 재작성 횟수
    status: str                 # "ok" | "failed_validation" | "rejected"
    saved_path: str             # save_storybook 툴이 저장한 파일 경로
    # 메모리 (thread별 누적)
    learned_words: Annotated[list[str], _union_words]  # 지금까지 배운 단어


# ── LLM 호출 (겸용: OpenAI ↔ Claude ↔ mock) ──────────────────
def _llm_provider() -> str | None:
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def _call_llm(prompt: str, max_tokens: int = 1500) -> str:
    provider = _llm_provider()
    if provider == "openai":
        from openai import OpenAI  # pip install openai

        resp = OpenAI().chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
    import anthropic  # pip install anthropic

    resp = anthropic.Anthropic().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def _object_particle(word: str) -> str:
    """한국어 목적격 조사 을/를 선택 (mock 문장 자연스럽게)."""
    ch = word[-1]
    if "가" <= ch <= "힣":
        return "을" if (ord(ch) - 0xAC00) % 28 else "를"
    return "를"


def _word_buckets(words: list[str], n_buckets: int) -> list[list[str]]:
    """단어를 본문 페이지에 라운드로빈 배치 (단어 수 > 페이지 수 대응)."""
    buckets: list[list[str]] = [[] for _ in range(n_buckets)]
    for i, w in enumerate(words):
        buckets[i % n_buckets].append(w)
    return buckets


def _page_count(words: list[str]) -> int:
    return min(MAX_PAGES, max(MIN_PAGES, len(words) + 1))


# ── 툴 ① : 단어 적합성 검사 (커스텀 툴) ──────────────────────
@tool
def check_words(words: list[str]) -> dict:
    """학습 단어 목록이 유아용 동화에 적합한지 검사한다.
    개수(5~10개), 한글 여부, 길이(1~5자), 금지어 포함 여부를 확인해
    {"ok": bool, "problems": [문제 설명]} 형태로 반환한다."""
    problems: list[str] = []
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        problems.append(f"단어 개수는 {MIN_WORDS}~{MAX_WORDS}개여야 합니다 (현재 {len(words)}개)")
    for w in words:
        if w in BANNED_WORDS:
            problems.append(f"'{w}'은(는) 유아 동화에 부적합한 단어입니다")
        elif not re.fullmatch(r"[가-힣]{1,5}", w):
            problems.append(f"'{w}'은(는) 1~5자의 한글 단어가 아닙니다")
    return {"ok": not problems, "problems": problems}


# ── 툴 ② : 동화책 파일 저장 (파일 툴) ────────────────────────
@tool
def save_storybook(title: str, pages: list[dict], illust_prompts: list[dict]) -> str:
    """완성된 동화(페이지 텍스트 + 페이지별 삽화 프롬프트)를
    output/<제목>.md 마크다운 파일로 저장하고 저장 경로를 반환한다."""
    out_dir = Path(__file__).resolve().parent.parent / "output"
    out_dir.mkdir(exist_ok=True)
    safe = re.sub(r"[^가-힣a-zA-Z0-9 _-]", "", title).strip() or "storybook"
    path = out_dir / f"{safe}.md"

    prompt_by_page = {p["page"]: p["prompt"] for p in illust_prompts}
    lines = [f"# {title}", ""]
    for p in sorted(pages, key=lambda x: x["page"]):
        lines += [f"## {p['page']}페이지", "", p["text"], ""]
        if p["page"] in prompt_by_page:
            lines += [f"> 삽화 프롬프트: {prompt_by_page[p['page']]}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── 노드 1: 단어 적합성 검사 (툴① 사용) ─────────────────────
def check_words_node(state: StoryState) -> dict:
    result = check_words.invoke({"words": state["target_words"]})
    return {"word_check": result}


# ── 노드 2: 입력 거절 안내 ───────────────────────────────────
def reject_input(state: StoryState) -> dict:
    return {"status": "rejected", "issues": state["word_check"]["problems"]}


# ── 노드 3: 스토리 플래닝 ────────────────────────────────────
def plan_story(state: StoryState) -> dict:
    words = state["target_words"]
    age, theme = state.get("child_age", 4), state.get("theme", "숲속 모험")
    hero = state.get("hero", HERO_DEFAULT)
    name = _hero_name(hero)

    # 메모리 활용: 이전 동화에서 배운 단어 중 1~2개를 복습으로 등장시킨다
    review = [w for w in state.get("learned_words", []) if w not in words][:2]

    if _llm_provider():
        review_note = f" 복습을 위해 {', '.join(review)}도 잠깐 등장시켜 줘." if review else ""
        plan = _call_llm(
            f"{age}세 유아용 동화 줄거리 개요를 5문장 이내로 써줘. "
            f"주인공은 '{hero}' 단 한 명이고, 반드시 이름 '{name}'(으)로만 불러줘 "
            f"('유아', '아이', '친구' 같은 일반 명사로 지칭 금지). "
            f"테마: {theme}. 반드시 이 단어들이 이야기에 등장해야 해: {', '.join(words)}."
            f"{review_note} 폭력적이거나 무서운 요소 없이 따뜻하게."
        )
        # 캐릭터 시트: 모든 페이지 삽화에서 동일하게 쓸 주인공 외형 묘사 (영어 1문장)
        sheet = _call_llm(
            f"유아 동화책 주인공 '{hero}'의 외형을 이미지 생성 프롬프트용 영어 한 문장으로 묘사해줘. "
            f'반드시 "the same main character on every page:"로 시작하고, 이름·색·복장을 고정해줘. '
            f"문장만 답해.",
            max_tokens=120,
        ).strip()
    else:  # mock
        review_note = f" 지난번에 배운 {', '.join(review)}도 반갑게 다시 만나요." if review else ""
        plan = (
            f"{hero} '{name}'이(가) {theme}을 떠나요. "
            f"길에서 {', '.join(words)}(을)를 하나씩 만나며 신나는 하루를 보내고,"
            f"{review_note} 저녁에 엄마 품으로 돌아와 포근히 잠들어요."
        )
        sheet = CHARACTER_SHEET_DEFAULT

    # 새 동화 시작: 이전 실행(같은 thread)의 검증/삽화 상태 초기화
    return {
        "story_plan": plan,
        "character_sheet": sheet,
        "retry_count": 0,
        "issues": [],
        "illust_prompts": None,
    }


# ── 노드 4a: 페이지 생성 — 영아용 (child_age ≤ 3) ────────────
ONOMATOPOEIA = ["폴짝폴짝!", "반짝반짝!", "살랑살랑!", "몽글몽글!", "데굴데굴!", "쫑긋쫑긋!"]


def write_pages_toddler(state: StoryState) -> dict:
    words = state["target_words"]
    n_pages = _page_count(words)
    name = _hero_name(state.get("hero", HERO_DEFAULT))

    if _llm_provider():
        raw = _call_llm(
            f"다음 개요로 {n_pages}페이지 영아(0~3세)용 동화를 써줘.\n개요: {state['story_plan']}\n"
            f"규칙: 페이지당 딱 1문장(아주 짧게), 의성어·의태어와 반복 표현 위주, "
            f"주인공은 모든 페이지에서 이름 '{name}'(으)로만 지칭('유아', '아이' 금지), "
            f"이 단어들을 모두 본문에 사용: {', '.join(words)}.\n"
            f'JSON 배열로만 답해: [{{"page": 1, "text": "..."}}, ...]'
        )
        pages: list[Page] = json.loads(re.search(r"\[.*\]", raw, re.S).group())
    else:  # mock: 페이지당 1문장 + 의성어
        buckets = _word_buckets(words, n_pages - 1)
        pages = [{"page": 1, "text": f"{name}가 아침에 눈을 떴어요. 까꿍!"}]
        for i, bucket in enumerate(buckets, start=2):
            w = bucket[0]
            extra = f" {bucket[1]}도 있네!" if len(bucket) > 1 else ""
            sound = ONOMATOPOEIA[(i - 2) % len(ONOMATOPOEIA)]
            pages.append({"page": i, "text": f"{w}{_object_particle(w)} 봐요. {sound}{extra}"})
        pages[-1]["text"] += " 코~ 잘 자요."

    return {"pages": pages}


# ── 노드 4b: 페이지 생성 — 표준 (child_age ≥ 4) ──────────────
def write_pages_standard(state: StoryState) -> dict:
    words = state["target_words"]
    n_pages = _page_count(words)
    hero = state.get("hero", HERO_DEFAULT)
    name = _hero_name(hero)

    if _llm_provider():
        raw = _call_llm(
            f"다음 개요로 {n_pages}페이지 유아 동화를 써줘.\n개요: {state['story_plan']}\n"
            f"규칙: 페이지당 1~2문장({MAX_CHARS_PER_PAGE}자 이내), "
            f"주인공은 '{hero}' 단 한 명 — 모든 페이지에서 이름 '{name}'(으)로만 지칭"
            f"('유아', '아이', '친구' 같은 일반 명사 금지), "
            f"이 단어들을 모두 본문에 사용: {', '.join(words)}.\n"
            f'JSON 배열로만 답해: [{{"page": 1, "text": "..."}}, ...]'
        )
        pages: list[Page] = json.loads(re.search(r"\[.*\]", raw, re.S).group())
    else:  # mock: 단어를 2페이지~마지막 페이지에 라운드로빈 배치
        buckets = _word_buckets(words, n_pages - 1)
        pages = [{"page": 1, "text": f"아침 해가 뜨자 {hero} {name}가 폴짝 일어났어요."}]
        for i, bucket in enumerate(buckets, start=2):
            parts = [f"{name}는 {w}{_object_particle(w)} 만나 활짝 웃었어요." for w in bucket]
            pages.append({"page": i, "text": " ".join(parts)})
        pages[-1]["text"] += f" {name}는 엄마 품에서 새근새근 잠들었답니다."

        # (데모) 첫 시도에서 마지막 단어를 일부러 빼서 검증→재작성 루프를 시연
        if state.get("demo_fail_first") and state.get("retry_count", 0) == 0:
            missing = words[-1]
            for p in pages:
                p["text"] = p["text"].replace(
                    f"{name}는 {missing}{_object_particle(missing)} 만나 활짝 웃었어요.", ""
                ).strip() or f"{name}가 깡충깡충 뛰어갔어요."

    return {"pages": pages}


# ── 노드 5: 검증 (규칙 기반, LLM 불필요) ─────────────────────
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


# ── 노드 6: 마무리 ───────────────────────────────────────────
def finalize(state: StoryState) -> dict:
    ok = not state.get("issues")
    update: dict = {"status": "ok" if ok else "failed_validation"}
    if ok:
        update["learned_words"] = state["target_words"]  # 메모리 누적 (union 리듀서)
    return update


# ── 노드 7: 페이지별 삽화 프롬프트 생성 (Send 병렬) ──────────
def gen_illust_prompt(payload: dict) -> dict:
    """finalize에서 Send로 페이지 수만큼 병렬 실행된다. payload는 페이지 1개 단위.

    캐릭터 일관성: 모든 페이지 프롬프트가 동일한 character_sheet(주인공 외형 묘사)로
    시작하므로, 이미지 생성 시 페이지마다 주인공이 달라지는 문제를 방지한다.
    """
    page: Page = payload["page"]
    theme = payload["theme"]
    sheet = payload.get("character_sheet", CHARACTER_SHEET_DEFAULT)

    if _llm_provider():
        prompt = _call_llm(
            f"유아 동화책 삽화 지시문을 영어 한 문장으로 써줘.\n"
            f'반드시 이 주인공 묘사로 시작해 (한 글자도 바꾸지 말 것): "{sheet}"\n'
            f"이어서 장면 묘사: {page['text']} (테마: {theme})\n"
            f"스타일: pastel watercolor, bright and cozy children's book illustration. 문장만 답해.",
            max_tokens=250,
        ).strip()
    else:  # mock
        prompt = (
            f"{sheet} — 장면: '{page['text']}' ({theme} 배경), "
            f"파스텔톤 수채화, 밝고 포근한 유아 동화책 삽화 스타일"
        )
    return {"illust_prompts": [{"page": page["page"], "prompt": prompt}]}


# ── 노드 8: 동화책 저장 (툴② 사용) ──────────────────────────
def save_storybook_node(state: StoryState) -> dict:
    title = f"{state.get('theme', '동화')} 이야기"
    path = save_storybook.invoke({
        "title": title,
        "pages": state["pages"],
        "illust_prompts": state.get("illust_prompts", []),
    })
    return {"saved_path": path}


# ── 조건부 엣지 ① : 단어 검사 결과 분기 ──────────────────────
def route_after_check(state: StoryState) -> Literal["reject_input", "plan_story"]:
    return "plan_story" if state["word_check"]["ok"] else "reject_input"


# ── 조건부 엣지 ② : 사용자 입력(나이)에 따른 작문 스타일 분기 ─
def route_by_age(state: StoryState) -> Literal["write_pages_toddler", "write_pages_standard"]:
    if state.get("child_age", 4) <= TODDLER_MAX_AGE:
        return "write_pages_toddler"
    return "write_pages_standard"


# ── 조건부 엣지 ③ : 검증 결과에 따라 재작성 루프 or 마무리 ───
def route_after_validation(
    state: StoryState,
) -> Literal["write_pages_toddler", "write_pages_standard", "finalize"]:
    if state.get("issues") and state.get("retry_count", 0) <= MAX_RETRIES:
        return route_by_age(state)   # 나이에 맞는 작성 노드로 재작성 루프
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
builder.add_node("check_words", check_words_node)
builder.add_node("reject_input", reject_input)
builder.add_node("plan_story", plan_story)
builder.add_node("write_pages_toddler", write_pages_toddler)
builder.add_node("write_pages_standard", write_pages_standard)
builder.add_node("validate_story", validate_story)
builder.add_node("finalize", finalize)
builder.add_node("gen_illust_prompt", gen_illust_prompt)
builder.add_node("save_storybook", save_storybook_node)

builder.add_edge(START, "check_words")
builder.add_conditional_edges("check_words", route_after_check)
builder.add_edge("reject_input", END)
builder.add_conditional_edges("plan_story", route_by_age)
builder.add_edge("write_pages_toddler", "validate_story")
builder.add_edge("write_pages_standard", "validate_story")
builder.add_conditional_edges("validate_story", route_after_validation)
builder.add_conditional_edges("finalize", fanout_illustrations, ["gen_illust_prompt"])
builder.add_edge("gen_illust_prompt", "save_storybook")
builder.add_edge("save_storybook", END)

# 메모리: thread_id별로 상태(learned_words 등)를 보존하는 체크포인터
graph = builder.compile(checkpointer=MemorySaver())


# ── 데모 실행 ────────────────────────────────────────────────
def _print_story(label: str, result: dict) -> None:
    print(f"--- {label} ---")
    print(f"[줄거리] {result['story_plan']}\n")
    for p in result["pages"]:
        print(f"  p{p['page']}. {p['text']}")
    print(f"\n[검증] 재작성 {result['retry_count']}회, 최종 상태: {result['status']}")
    if result.get("issues"):
        print(f"[남은 문제] {result['issues']}")
    print(f"[삽화 프롬프트] {len(result.get('illust_prompts', []))}개 병렬 생성")
    for ip in sorted(result.get("illust_prompts", []), key=lambda x: x["page"])[:2]:
        print(f"  p{ip['page']}: {ip['prompt']}")
    print(f"[저장] {result.get('saved_path')}")
    print(f"[메모리] 지금까지 배운 단어: {result.get('learned_words')}\n")


if __name__ == "__main__":
    try:
        import dotenv

        dotenv.load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass

    mode = _llm_provider() or "mock"
    print(f"=== WordiTale 실행 (LLM 모드: {mode}) ===\n")

    # 아이별 세션: 같은 thread_id면 배운 단어가 누적된다 (메모리)
    yeonu = {"configurable": {"thread_id": "child-yeonu"}}

    # ① 4세 표준 스타일 + 검증 실패 → 재작성 루프 시연
    r1 = graph.invoke({
        "target_words": ["사과", "구름", "나비", "바람", "무지개", "달팽이"],
        "child_age": 4,
        "theme": "숲속 모험",
        "demo_fail_first": True,
    }, yeonu)
    _print_story("동화 1: 4세 · 숲속 모험 (재작성 루프 시연)", r1)

    # ② 같은 아이, 3세 영아 스타일 → 나이 분기 + 메모리(배운 단어 누적) 시연
    r2 = graph.invoke({
        "target_words": ["물고기", "거북이", "소라", "파도", "진주"],
        "child_age": 3,
        "theme": "바닷속 여행",
        "demo_fail_first": False,
    }, yeonu)
    _print_story("동화 2: 3세 · 바닷속 여행 (영아 스타일 + 복습 단어)", r2)

    # ③ 부적합 단어 포함 → check_words 툴이 거절하는 분기 시연
    r3 = graph.invoke({
        "target_words": ["사과", "칼", "나비", "바람", "구름"],
        "child_age": 4,
        "theme": "숲속 모험",
    }, {"configurable": {"thread_id": "reject-demo"}})
    print("--- 동화 3: 부적합 단어 → 입력 거절 시연 ---")
    print(f"[상태] {r3['status']}")
    print(f"[사유] {r3['issues']}")
