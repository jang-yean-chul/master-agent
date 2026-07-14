"""그래프 노드 함수 — 오케스트레이터 / 페이지 워커 / 검증 / 삽화 / 저장.

각 노드는 LLM 키가 있으면 실제 생성, 없으면 mock(규칙 기반)으로 동작한다.
"""
from __future__ import annotations

import json
import re

from worditale.config import (
    CHARACTER_SHEET_DEFAULT,
    HERO_DEFAULT,
    MAX_CHARS_PER_PAGE,
    MAX_PAGES,
    MIN_PAGES,
    hero_name,
)
from worditale.llm import call_llm, llm_provider
from worditale.state import Page, PageBrief, StoryState
from worditale.tools import check_words, save_storybook

# ── 한국어/배치 헬퍼 ─────────────────────────────────────────
ONOMATOPOEIA = ["폴짝폴짝!", "반짝반짝!", "살랑살랑!", "몽글몽글!", "데굴데굴!", "쫑긋쫑긋!"]


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


# ── 노드 1: 단어 적합성 검사 (툴① 사용) ─────────────────────
def check_words_node(state: StoryState) -> dict:
    result = check_words.invoke({"words": state["target_words"]})
    return {"word_check": result}


# ── 노드 2: 입력 거절 안내 ───────────────────────────────────
def reject_input(state: StoryState) -> dict:
    return {"status": "rejected", "issues": state["word_check"]["problems"]}


# ── 노드 3: 오케스트레이터 — 줄거리 + 페이지별 브리프 설계 ───
def _rule_briefs(words: list[str], theme: str, name: str) -> list[PageBrief]:
    """규칙 기반 브리프 (mock 모드 + LLM 출력이 범위를 벗어났을 때의 안전망)."""
    n_pages = _page_count(words)
    buckets = _word_buckets(words, n_pages - 1)
    briefs: list[PageBrief] = [{
        "page": 1, "role": "도입",
        "scene": f"{name}가 아침에 일어나 {theme}을 떠날 준비를 한다", "words": [],
    }]
    for i, bucket in enumerate(buckets, start=2):
        briefs.append({
            "page": i,
            "role": "마무리" if i == n_pages else "전개",
            "scene": f"{name}가 {', '.join(bucket)}을(를) 만난다",
            "words": bucket,
        })
    briefs[-1]["scene"] += " · 하루를 마치고 포근하게 잠든다"
    return briefs


def plan_story(state: StoryState) -> dict:
    """오케스트레이터: 줄거리와 함께 페이지 수·단어 배치·페이지별 장면(브리프)을
    동적으로 계획한다. 서사의 흐름(이음새 포함)은 전부 여기서 결정되고,
    페이지 워커들은 브리프대로 문장만 렌더링한다."""
    words = state["target_words"]
    age, theme = state.get("child_age", 4), state.get("theme", "숲속 모험")
    hero = state.get("hero", HERO_DEFAULT)
    name = hero_name(hero)

    # 메모리 활용: 이전 동화에서 배운 단어 중 1~2개를 복습으로 등장시킨다
    review = [w for w in state.get("learned_words", []) if w not in words][:2]

    if llm_provider():
        review_note = f" 복습을 위해 {', '.join(review)}도 잠깐 등장시켜 줘." if review else ""
        raw = call_llm(
            f"{age}세 유아용 동화를 기획해줘. "
            f"주인공은 '{hero}' 단 한 명이고, 반드시 이름 '{name}'(으)로만 불러줘 "
            f"('유아', '아이', '친구' 같은 일반 명사로 지칭 금지). "
            f"테마: {theme}. 반드시 이 학습 단어를 모두 사용: {', '.join(words)}."
            f"{review_note} 폭력적이거나 무서운 요소 없이 따뜻하게.\n"
            f"페이지 수는 {MIN_PAGES}~{MAX_PAGES} 사이에서 네가 정하고, "
            f"학습 단어를 페이지별로 나눠 배치해 (1페이지는 도입이라 단어가 없어도 돼). "
            f"scene은 사건 순서대로 한 장면씩 — 서로 내용이 겹치지 않게, "
            f"앞 페이지에서 자연스럽게 이어지도록 써.\n"
            f"JSON으로만 답해: "
            f'{{"plan": "줄거리 5문장 이내", "pages": [{{"page": 1, "role": "도입|전개|마무리", '
            f'"scene": "이 페이지에서 벌어지는 일 한 줄", "words": ["배치된 학습 단어"]}}, ...]}}'
        )
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group())
        plan = data["plan"]
        briefs: list[PageBrief] = data["pages"]

        # 안전망: 페이지 번호 정규화 + 개수 범위 + 단어 커버리지 보정
        for i, b in enumerate(briefs, start=1):
            b["page"] = i
            b.setdefault("role", "전개")
            b.setdefault("words", [])
        if not (MIN_PAGES <= len(briefs) <= MAX_PAGES):
            briefs = _rule_briefs(words, theme, name)
        assigned = {w for b in briefs for w in b["words"]}
        missing = [w for w in words if w not in assigned]
        if missing:  # 오케스트레이터가 빠뜨린 단어는 마지막 페이지에 배치
            briefs[-1]["words"] = list(briefs[-1]["words"]) + missing

        # 캐릭터 시트: 모든 페이지 삽화에서 동일하게 쓸 주인공 외형 묘사 (영어 1문장)
        sheet = call_llm(
            f"유아 동화책 주인공 '{hero}'의 외형을 이미지 생성 프롬프트용 영어 한 문장으로 묘사해줘. "
            f'반드시 "the same main character on every page:"로 시작하고, 이름·색·복장을 고정해줘. '
            f"문장만 답해.",
            max_tokens=120,
        ).strip()
    else:  # mock
        review_note = f" 지난번에 배운 {', '.join(review)}도 반갑게 다시 만나요." if review else ""
        plan = (
            f"{hero}가 {theme}을 떠나요. "
            f"길에서 {', '.join(words)}(을)를 하나씩 만나며 신나는 하루를 보내고,"
            f"{review_note} 저녁에 엄마 품으로 돌아와 포근히 잠들어요."
        )
        briefs = _rule_briefs(words, theme, name)
        sheet = CHARACTER_SHEET_DEFAULT

    # 새 동화 시작: 이전 실행(같은 thread)의 페이지/검증/삽화 상태 초기화
    return {
        "story_plan": plan,
        "page_briefs": briefs,
        "character_sheet": sheet,
        "pages": None,
        "retry_count": 0,
        "issues": [],
        "illust_prompts": None,
    }


# ── 노드 4a/4b: 페이지 워커 (Send 병렬 — 브리프 1개 = 페이지 1개) ─
def _worker_context(payload: dict) -> str:
    """워커 공통 프롬프트: 전체 줄거리 + 자기 브리프 + 앞뒤 장면 요약.
    이음새를 오케스트레이터가 정한 대로 쓰게 해 병렬 작성에도 흐름을 유지한다.
    앞뒤 장면은 '참고용'임을 명시 — 다시 쓰거나 미리 쓰면 페이지끼리 내용이 겹친다."""
    brief: PageBrief = payload["brief"]
    return (
        f"전체 줄거리: {payload['story_plan']}\n"
        f"이 페이지: p{brief['page']} ({brief['role']}) — 장면: {brief['scene']}\n"
        f"직전 페이지 장면(참고만, 이미 앞 페이지에 쓰여 있으니 다시 서술 금지): "
        f"{payload.get('prev_scene') or '없음 (첫 페이지 — 이야기의 시작)'}\n"
        f"다음 페이지 장면(참고만, 다음 페이지가 쓸 내용이니 미리 서술 금지): "
        f"{payload.get('next_scene') or '없음 (마지막 페이지 — 포근하게 끝맺기)'}\n"
        f"오직 이 페이지의 장면만 써.\n"
    )


def write_page_toddler(payload: dict) -> dict:
    """영아용(≤3세) 페이지 워커: 의성어 중심 딱 1문장."""
    brief: PageBrief = payload["brief"]
    name = hero_name(payload.get("hero", HERO_DEFAULT))
    words = [w for w in brief["words"] if w != payload.get("demo_drop_word")]

    if llm_provider():
        text = call_llm(
            f"영아(0~3세)용 동화의 한 페이지만 써줘.\n{_worker_context(payload)}"
            f"규칙: 딱 1문장(10단어 이내로 아주 짧게), 의성어·의태어 위주, "
            f"문체는 '~해요/~했어요'(해요체)로 통일, "
            f"주인공은 이름 '{name}'(으)로만 지칭 — 수식어구를 붙이지 마"
            f"('유아', '아이' 같은 일반 명사도 금지), "
            f"반드시 이 단어를 본문에 포함: {', '.join(words) or '(없음)'}. "
            f"페이지 본문 텍스트만 답해.",
            max_tokens=150,
        ).strip()
    else:  # mock
        if not words:
            text = f"{name}가 아침에 눈을 떴어요. 까꿍!" if brief["role"] == "도입" \
                else f"{name}가 깡충깡충 뛰어가요!"
        else:
            extra = f" {words[1]}도 있네!" if len(words) > 1 else ""
            sound = ONOMATOPOEIA[(brief["page"] - 2) % len(ONOMATOPOEIA)]
            text = f"{words[0]}{_object_particle(words[0])} 봐요. {sound}{extra}"
        if payload.get("next_scene") is None:
            text += " 코~ 잘 자요."

    return {"pages": [{"page": brief["page"], "text": text}]}


def write_page_standard(payload: dict) -> dict:
    """표준(≥4세) 페이지 워커: 이야기 중심 1~2문장."""
    brief: PageBrief = payload["brief"]
    hero = payload.get("hero", HERO_DEFAULT)
    name = hero_name(hero)
    words = [w for w in brief["words"] if w != payload.get("demo_drop_word")]

    if llm_provider():
        text = call_llm(
            f"유아 동화의 한 페이지만 써줘.\n{_worker_context(payload)}"
            f"규칙: 최대 2문장, 전체 80자 이내(꼭 지켜), "
            f"문체는 '~해요/~했어요'(해요체)로 통일, "
            f"주인공은 이름 '{name}'(으)로만 지칭 — 수식어구 '{hero}'를 문장 앞에 반복하지 마 "
            f"('유아', '아이', '친구' 같은 일반 명사도 금지), "
            f"반드시 이 단어를 본문에 포함: {', '.join(words) or '(없음)'}. "
            f"페이지 본문 텍스트만 답해.",
            max_tokens=200,
        ).strip()
    else:  # mock
        if not words:
            text = f"아침 해가 뜨자 {hero}가 폴짝 일어났어요." if brief["role"] == "도입" \
                else f"{name}가 깡충깡충 뛰어갔어요."
        else:
            text = " ".join(f"{name}는 {w}{_object_particle(w)} 만나 활짝 웃었어요." for w in words)
        if payload.get("next_scene") is None:
            text += f" {name}는 엄마 품에서 새근새근 잠들었답니다."

    return {"pages": [{"page": brief["page"], "text": text}]}


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

    if llm_provider():
        prompt = call_llm(
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
