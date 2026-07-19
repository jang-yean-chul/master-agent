"""그래프 노드 함수 — 오케스트레이터 / 페이지 워커 / 검증 / 삽화 / 저장.

각 노드는 LLM 키가 있으면 실제 생성, 없으면 mock(규칙 기반)으로 동작한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from worditale.config import (
    BANNED_WORDS,
    CHARACTER_SHEET_DEFAULT,
    HERO_DEFAULT,
    ILLUST_STYLE,
    MAX_CHARS_PER_PAGE,
    MAX_PAGES,
    MIN_PAGES,
    THEME_DEFAULT,
    hero_name,
)
from worditale.imaging import caption_image
from worditale.llm import (
    call_llm,
    edit_image_with_reference,
    generate_image,
    image_provider,
    llm_provider,
)
from worditale.state import Page, PageBrief, StoryState
from worditale.tools import check_words, save_storybook

# ── 한국어/배치 헬퍼 ─────────────────────────────────────────
ONOMATOPOEIA = ["폴짝폴짝!", "반짝반짝!", "살랑살랑!", "몽글몽글!", "데굴데굴!", "쫑긋쫑긋!"]

# LLM 응답에서 JSON 블록만 추출 (앞뒤 사족 무시)
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


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
        "page": 1, "role": "도입", "why": "이야기의 시작",
        "scene": f"{name}가 아침에 일어나 {theme}을 떠날 준비를 한다", "words": [],
    }]
    for i, bucket in enumerate(buckets, start=2):
        briefs.append({
            "page": i,
            "role": "마무리" if i == n_pages else "전개",
            "why": "앞 장면에서 길을 나선 결과로 이어진다",
            "scene": f"{name}가 {', '.join(bucket)}을(를) 만난다",
            "words": bucket,
        })
    briefs[-1]["scene"] += " · 하루를 마치고 포근하게 잠든다"
    return briefs


def _llm_plan(
    state: StoryState, words: list[str], theme: str, hero: str, name: str,
    review: list[str], replan: bool,
) -> tuple[str, list[PageBrief], str]:
    """LLM 기획: (줄거리, 브리프, 캐릭터 시트)를 만든다 — 규격 밖 출력은 보정."""
    age = state.get("child_age", 4)
    review_note = f" 복습을 위해 {', '.join(review)}도 잠깐 등장시켜 줘." if review else ""
    feedback = ""
    if replan:
        feedback = (
            f"\n직전 설계로 만든 이야기가 이 문제로 불합격했어 — 설계를 완전히 새로 해: "
            f"{'; '.join(state['issues'])}"
        )
    raw = call_llm(
            f"{age}세 유아용 동화를 기획해줘. "
            f"주인공은 '{hero}' 단 한 명이고, 반드시 이름 '{name}'(으)로만 불러줘 "
            f"('유아', '아이', '친구' 같은 일반 명사로 지칭 금지). "
            f"테마: {theme}. 반드시 이 학습 단어를 모두 사용: {', '.join(words)}."
            f"{review_note} 폭력적이거나 무서운 요소 없이 따뜻하게.{feedback}\n"
            f"이야기 규칙 (가장 중요 — '단어 나열'이 아니라 기승전결이 있는 '이야기'여야 해):\n"
            f"- [기] 1페이지에서 {name}의 소망이나 문제를 '구체적으로' 하나 세워 — "
            f"'멋진 것을 보고 싶다' 같은 막연한 것 말고, "
            f"'무지개를 만져보고 싶다'처럼 아이가 그림으로 떠올릴 수 있는 것\n"
            f"- [승] 학습 단어는 그 소망을 이루러 가는 길의 '사건'으로 등장시켜 — "
            f"'{name}가 OO를 만나 인사했어요' 식으로 만나고 지나가는 나열 금지. "
            f"각 사건은 반드시 앞 사건 '때문에' 일어나야 해 "
            f"(장면 순서를 바꾸면 이야기가 깨질 정도로 촘촘하게)\n"
            f"- [전] 중간에 작은 어려움을 하나 만들고, 그 어려움은 반드시 다음 장면에서 "
            f"'해결'돼야 해 — 걱정만 던져놓고 잊어버린 채 다른 사건으로 넘어가는 것 금지\n"
            f"- [결] 마지막 페이지에서 1페이지의 소망/문제가 눈에 보이게 이뤄지고, "
            f"포근하게 잠들며 마무리\n"
            f"페이지 수는 {MIN_PAGES}~{MAX_PAGES} 사이에서 네가 정하고, "
            f"학습 단어를 페이지별로 나눠 배치해 (1페이지는 도입이라 단어가 없어도 돼). "
            f"scene은 사건 순서대로 한 장면씩 — 서로 내용이 겹치지 않게.\n"
            f"JSON으로만 답해: "
            f'{{"problem": "{name}의 구체적 소망/문제 한 줄", '
            f'"resolution": "마지막에 그것이 어떻게 이뤄지는지 한 줄", '
            f'"plan": "줄거리 5문장 이내 (소망→사건들→어려움과 해결→소망 성취 순서로)", '
            f'"pages": [{{"page": 1, "role": "도입|전개|마무리", '
            f'"scene": "이 페이지에서 벌어지는 일 한 줄", '
            f'"why": "앞 페이지의 무엇 때문에 이 장면이 일어나는지 한 줄 (1페이지는 \'시작\')", '
            f'"words": ["배치된 학습 단어"]}}, ...]}}'
    )
    data = json.loads(_JSON_BLOCK.search(raw).group())
    plan = data["plan"]
    problem = str(data.get("problem", "")).strip()
    resolution = str(data.get("resolution", "")).strip()
    if problem and resolution:  # 집필·검증이 서사의 뼈대를 계속 참조하도록 줄거리에 고정
        plan = f"{plan} (소망/문제: {problem} → 해결: {resolution})"
    briefs: list[PageBrief] = data["pages"]

    # 안전망: 페이지 번호 정규화 + 개수 범위 + 단어 커버리지 보정
    for i, b in enumerate(briefs, start=1):
        b["page"] = i
        b.setdefault("role", "전개")
        b.setdefault("why", "")
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
    return plan, briefs, sheet


def plan_story(state: StoryState) -> dict:
    """오케스트레이터: 줄거리와 함께 페이지 수·단어 배치·페이지별 장면(브리프)을
    동적으로 계획한다. 서사의 흐름(기승전결·인과 사슬)은 전부 여기서 결정되고,
    집필은 브리프대로 문장만 렌더링한다."""
    words = state["target_words"]
    theme = state.get("theme", THEME_DEFAULT)
    hero = state.get("hero", HERO_DEFAULT)
    name = hero_name(hero)

    # 메모리 활용: 이전 동화에서 배운 단어 중 1~2개를 복습으로 등장시킨다
    review = [w for w in state.get("learned_words", []) if w not in words][:2]

    # 서사 재계획: 검증에서 '서사 문제'가 나오면 집필이 아니라 여기(설계)로 되돌아온다.
    # 그때는 지난 설계의 문제를 피드백으로 넣고, retry_count를 보존해 루프 상한을 지킨다.
    replan = bool(state.get("needs_replan") and state.get("issues"))

    if llm_provider():
        plan, briefs, sheet = _llm_plan(state, words, theme, hero, name, review, replan)
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
        "retry_count": state.get("retry_count", 0) if replan else 0,
        "issues": [],
        "needs_replan": False,
        "illust_prompts": None,
    }


# ── 노드 4a/4b: 이야기 전체 집필 (나이 분기 — 한 호흡으로 작성) ─
# 페이지를 병렬 워커로 쪼개 쓰면 문장 이음새가 끊긴다(2026-07-18 사용자 피드백).
# 브리프(설계)는 유지하되 집필은 한 콜로 — 병렬성은 삽화 생성이 담당한다.
def _mock_page_toddler(brief: PageBrief, name: str, words: list[str], is_last: bool) -> str:
    if not words:
        text = f"{name}가 아침에 눈을 떴어요. 까꿍!" if brief["role"] == "도입" \
            else f"{name}가 깡충깡충 뛰어가요!"
    else:
        extra = f" {words[1]}도 있네!" if len(words) > 1 else ""
        sound = ONOMATOPOEIA[(brief["page"] - 2) % len(ONOMATOPOEIA)]
        text = f"{words[0]}{_object_particle(words[0])} 봐요. {sound}{extra}"
    if is_last:
        text += " 코~ 잘 자요."
    return text


def _mock_page_standard(brief: PageBrief, hero: str, name: str, words: list[str], is_last: bool) -> str:
    if not words:
        text = f"아침 해가 뜨자 {hero}가 폴짝 일어났어요." if brief["role"] == "도입" \
            else f"{name}가 깡충깡충 뛰어갔어요."
    else:
        text = " ".join(f"{name}는 {w}{_object_particle(w)} 만나 활짝 웃었어요." for w in words)
    if is_last:
        text += f" {name}는 엄마 품에서 새근새근 잠들었답니다."
    return text


def _write_story(state: StoryState, style: str) -> dict:
    """브리프 전체를 받아 동화를 처음부터 끝까지 한 호흡으로 쓴다.

    style: "toddler"(≤3세, 의성어 1문장) | "standard"(≥4세, 1~2문장).
    LLM 출력이 규격(페이지 수)을 벗어나면 mock 로직으로 폴백한다.
    """
    briefs: list[PageBrief] = state["page_briefs"]
    hero = state.get("hero", HERO_DEFAULT)
    name = hero_name(hero)

    # (데모, mock 전용) 첫 시도에 마지막 단어를 빼서 검증→재작성 루프 시연
    drop = None
    if not llm_provider() and state.get("demo_fail_first") and state.get("retry_count", 0) == 0:
        drop = state["target_words"][-1]

    if llm_provider():
        style_rules = (
            "페이지마다 딱 1문장(10단어 이내로 아주 짧게), 의성어·의태어 위주"
            if style == "toddler"
            else "페이지마다 최대 2문장, 페이지당 80자 이내(꼭 지켜)"
        )
        feedback = ""
        if state.get("issues"):
            feedback = f"\n지난 시도의 문제 (이번엔 반드시 고쳐): {'; '.join(state['issues'])}"
        briefs_json = json.dumps(
            [{"page": b["page"], "scene": b["scene"], "why": b.get("why", ""),
              "words": b["words"]} for b in briefs],
            ensure_ascii=False,
        )
        raw = call_llm(
            f"유아 동화 전체를 처음부터 끝까지 한 호흡으로 써줘.\n"
            f"전체 줄거리: {state.get('story_plan', '')}\n"
            f"페이지 설계(순서·장면·인과·배치 단어): {briefs_json}\n"
            f"규칙:\n"
            f"- {style_rules}\n"
            f"- 문체는 '~해요/~했어요'(해요체)로 통일\n"
            f"- 주인공은 이름 '{name}'(으)로만 지칭 — 수식어구 '{hero}' 반복 금지, "
            f"'유아'·'아이'·'친구' 같은 일반 명사 금지\n"
            f"- 각 페이지에 배치된 words를 그 페이지 본문에 반드시 포함\n"
            f"- 각 페이지는 설계의 why(앞 페이지와의 인과)가 본문에서 실제로 느껴지게 써 — "
            f"'그래서/그런데'를 기계적으로 붙이는 게 아니라, 앞 페이지의 사건 '때문에' "
            f"이번 사건이 일어났음이 문장 내용으로 드러나야 해\n"
            f"- 마지막 페이지는 1페이지의 소망/문제가 이뤄진 것을 보여주고 포근하게 잠들며 끝맺기{feedback}\n"
            f'JSON으로만 답해: {{"pages": [{{"page": 1, "text": "본문"}}, ...]}} '
            f"(페이지 수는 설계와 동일하게 {len(briefs)}개)",
            max_tokens=2000,
        )
        try:
            data = json.loads(_JSON_BLOCK.search(raw).group())
            pages = [
                {"page": i, "text": str(p["text"]).strip()}
                for i, p in enumerate(data["pages"], start=1)
            ]
            if len(pages) == len(briefs):
                return {"pages": pages}
        except Exception:
            pass  # 규격 밖 출력 → 아래 mock 폴백

    pages = []
    for i, brief in enumerate(briefs):
        words = [w for w in brief["words"] if w != drop]
        is_last = i == len(briefs) - 1
        if style == "toddler":
            text = _mock_page_toddler(brief, name, words, is_last)
        else:
            text = _mock_page_standard(brief, hero, name, words, is_last)
        pages.append({"page": brief["page"], "text": text})
    return {"pages": pages}


def write_story_toddler(state: StoryState) -> dict:
    """영아용(≤3세) 집필: 의성어 중심 짧은 문장으로 전체 작성."""
    return _write_story(state, "toddler")


def write_story_standard(state: StoryState) -> dict:
    """표준(≥4세) 집필: 이야기 중심 문장으로 전체 작성."""
    return _write_story(state, "standard")


# ── 노드 5: 검증 게이트 — 규칙 검사 + 출력 안전성 검사 ───────
def _llm_judge_story(full_text: str) -> str | None:
    """출력 안전성 2차 검사: 생성된 본문을 LLM이 유아 적합성 기준으로 판정.
    문제가 있으면 사유 문자열, 없거나 판정 실패면 None."""
    try:
        raw = call_llm(
            f"다음 유아(3~7세) 동화 본문에 부적절한 요소"
            f"(폭력·공포·죽음·성인 소재·차별/혐오)가 있는지 검사해줘.\n"
            f"본문: {full_text}\n"
            f'JSON으로만 답해: {{"safe": true 또는 false, "reason": "문제가 있으면 이유 한 줄"}}',
            max_tokens=150,
        )
        data = json.loads(_JSON_BLOCK.search(raw).group())
        if not data.get("safe", True):
            return data.get("reason", "유아 부적합 요소 감지")
    except Exception:
        pass  # 판정 실패 시 규칙 검사 결과만 사용
    return None


def _llm_judge_narrative(pages: list[Page], story_plan: str) -> str | None:
    """서사 품질 검사: 기승전결·인과 연결을 LLM이 판정 (2026-07-20 사용자 피드백 —
    연결어만 있고 실제 인과가 없는 '장면 나열'이 통과되는 문제).
    문제가 있으면 사유 문자열, 없거나 판정 실패면 None."""
    try:
        raw = call_llm(
            f"다음 유아 동화가 '하나의 이야기'로 읽히는지 엄격하게 검사해줘.\n"
            f"설계된 줄거리: {story_plan}\n"
            f"본문: {json.dumps(pages, ensure_ascii=False)}\n"
            f"불합격 기준 (하나라도 해당하면 불합격):\n"
            f"- 페이지가 앞 페이지의 결과로 이어지지 않고 장면만 나열됨 "
            f"('그래서/그런데' 같은 연결어만 있고 실제 인과가 없는 경우 포함)\n"
            f"- 초반에 세운 소망·문제·걱정이 해결되지 않은 채 사라짐\n"
            f"- 마지막 페이지가 소망/문제의 해결 없이 갑자기 끝남\n"
            f'JSON으로만 답해: {{"ok": true 또는 false, '
            f'"reason": "불합격이면 어느 페이지 사이가 왜 끊기는지 한 줄"}}',
            max_tokens=250,
        )
        data = json.loads(_JSON_BLOCK.search(raw).group())
        if not data.get("ok", True):
            return data.get("reason", "페이지 사이 인과 연결 부족")
    except Exception:
        pass  # 판정 실패 시 통과 취급 (규칙 검사는 이미 끝남)
    return None


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

    # 출력 안전성 ①: 본문 금지어 스캔 (무료, mock에서도 동작)
    # ※ 1글자 금지어(칼/술/피 등)는 '칼국수', '술래잡기' 같은 오탐 때문에 제외
    banned_in_text = [w for w in BANNED_WORDS if len(w) >= 2 and w in full_text]
    if banned_in_text:
        issues.append(f"본문에 부적절 단어 포함: {', '.join(banned_in_text)}")

    # 출력 안전성 ② + 서사 품질: LLM 의미 판정 (키 있고 규칙 위반이 없을 때만)
    needs_replan = False
    if not issues and llm_provider():
        issue, needs_replan = _llm_output_checks(pages, full_text, state)
        if issue:
            issues.append(issue)

    update: dict = {"issues": issues, "needs_replan": needs_replan}
    if issues:
        update["retry_count"] = state.get("retry_count", 0) + 1
    return update


def _llm_output_checks(pages: list[Page], full_text: str, state: StoryState) -> tuple[str | None, bool]:
    """LLM 2차 판정 묶음: (문제 문자열, 재계획 필요 여부).

    안전성 문제 → 집필 재시도로 해결 가능 (needs_replan=False).
    서사(인과·기승전결) 문제 → 원인이 브리프(설계)에 있으므로
    설계부터 다시 하도록 needs_replan=True.
    """
    reason = _llm_judge_story(full_text)
    if reason:
        return f"본문 안전성 문제: {reason}", False
    reason = _llm_judge_narrative(pages, state.get("story_plan", ""))
    if reason:
        return f"서사 문제: {reason}", True
    return None, False


# ── 노드 6: 이음새 다듬기 (검증 통과 후 품질 패스) ───────────
def polish_story(state: StoryState) -> dict:
    """완성된 동화를 한 번 통독하며 페이지 사이 흐름만 다듬는다.

    안전망: 다듬은 결과가 페이지 수·학습 단어·길이 규칙을 하나라도 깨면
    버리고 원본을 유지한다 (다듬기가 검증을 무효화하면 안 됨).
    mock 모드이거나 검증 문제가 남아 있으면 아무것도 하지 않는다.
    """
    pages = state.get("pages") or []
    words = state.get("target_words", [])
    if not llm_provider() or not pages or state.get("issues"):
        return {}
    try:
        raw = call_llm(
            f"다음 유아 동화의 '흐름'만 다듬어줘 — 감정과 사건의 연속성, 급한 전환 보정. "
            f"주의: '그래서/그런데' 같은 연결어를 기계적으로 붙이지 마 — 연결어는 앞 문장과의 "
            f"인과가 본문 내용으로 실제 드러날 때만 써. 내용·사건 자체는 바꾸지 마.\n"
            f"지켜야 할 것: 페이지 수 {len(pages)}개 그대로, "
            f"학습 단어({', '.join(words)})는 한 개도 빼지 말 것, "
            f"페이지당 {MAX_CHARS_PER_PAGE}자 이내, 해요체 유지.\n"
            f"동화: {json.dumps(pages, ensure_ascii=False)}\n"
            f'JSON으로만 답해: {{"pages": [{{"page": 1, "text": "본문"}}, ...]}}',
            max_tokens=2000,
        )
        data = json.loads(_JSON_BLOCK.search(raw).group())
        new_pages = [
            {"page": i, "text": str(p["text"]).strip()}
            for i, p in enumerate(data["pages"], start=1)
        ]
        full = " ".join(p["text"] for p in new_pages)
        if (
            len(new_pages) == len(pages)
            and all(w in full for w in words)
            and all(len(p["text"]) <= MAX_CHARS_PER_PAGE for p in new_pages)
        ):
            return {"pages": new_pages}
    except Exception:
        pass  # 다듬기 실패 → 원본 유지
    return {}


# ── 노드 7: 마무리 ───────────────────────────────────────────
def finalize(state: StoryState) -> dict:
    ok = not state.get("issues")
    # needs_replan 정리: 재시도 소진으로 실패한 채 남은 플래그가
    # 다음 동화의 plan_story를 재계획 모드로 오인하게 하면 안 됨
    update: dict = {"status": "ok" if ok else "failed_validation", "needs_replan": False}
    if ok:
        update["learned_words"] = state["target_words"]  # 메모리 누적 (union 리듀서)
    return update


# ── 노드 8: 삽화 연출 계획 (그림 이음새 — 전체 연출 한 콜) ───
def plan_illustrations(state: StoryState) -> dict:
    """페이지별 삽화 장면을 한 콜로 함께 설계한다 (글의 '전체 집필'과 같은 원리).

    페이지마다 독립적으로 장면을 만들면 배경·시간대·소품이 제각각이 된다.
    연출 계획이 같은 장소 유지·시간 진행·소품 연속성을 보장하고,
    배경 기준 이미지용 세계관 묘사(setting_sheet)도 함께 만든다.
    mock 모드거나 규격 밖 출력이면 페이지 텍스트 기반 단순 장면으로 폴백.
    """
    pages = state.get("pages") or []
    theme = state.get("theme", THEME_DEFAULT)
    name = hero_name(state.get("hero", HERO_DEFAULT))
    fallback = {
        "illust_scenes": [
            {"page": p["page"], "scene": f"{name} — 장면: '{p['text']}' ({theme} 배경)"}
            for p in pages
        ],
        "setting_sheet": f"a warm, cozy storybook world for the theme '{theme}'",
    }
    if not llm_provider() or not pages:
        return fallback
    try:
        story = json.dumps(pages, ensure_ascii=False)
        raw = call_llm(
            f"유아 동화책의 페이지별 삽화 연출을 '전체를 함께' 설계해줘.\n"
            f"동화(테마 '{theme}', 주인공 이름 '{name}'): {story}\n"
            f"규칙:\n"
            f"- scene은 영어 한 문장, 주인공은 '{name}'(으)로 지칭, 행동 하나에 집중, 배경 요소 최대 2개\n"
            f"- 같은 장소에서 벌어지는 페이지는 배경 묘사를 동일하게 유지해 "
            f"(예: 'the same sunny meadow as before')\n"
            f"- 시간대는 이야기 흐름대로 자연스럽게 진행 (아침→낮→저녁), 갑자기 바뀌지 않게\n"
            f"- 앞 페이지에 등장한 소품·조연이 이어지는 장면이면 그대로 이어서 그려\n"
            f"- 화풍·색감 형용사(watercolor, vibrant, cozy 등)는 절대 쓰지 마 — 스타일은 따로 정해져 있어\n"
            f"- setting은 이 동화 세계관의 기준 배경 묘사(영어 한 문장, 캐릭터 없이 장소만)\n"
            f'JSON으로만 답해: {{"setting": "...", '
            f'"scenes": [{{"page": 1, "scene": "..."}}, ...]}} (페이지 수 {len(pages)}개 그대로)',
            max_tokens=1500,
        )
        data = json.loads(_JSON_BLOCK.search(raw).group())
        scenes = [
            {"page": i, "scene": str(s["scene"]).strip()}
            for i, s in enumerate(data["scenes"], start=1)
        ]
        if len(scenes) == len(pages):
            setting = str(data.get("setting", "")).strip() or fallback["setting_sheet"]
            return {"illust_scenes": scenes, "setting_sheet": setting}
    except Exception:
        pass
    return fallback


# ── 노드 9: 기준 이미지 생성 (캐릭터 + 배경 — 일관성의 앵커) ─
def _save_illustration(theme: str, name: str, data: bytes) -> str:
    """삽화 PNG를 output/images/<테마>/<이름>.png에 저장하고 경로를 반환."""
    from worditale import tools  # PROJECT_ROOT를 모듈 참조로 — 테스트 격리(monkeypatch) 반영

    safe = re.sub(r"[^가-힣a-zA-Z0-9 _-]", "", theme).strip() or "storybook"
    img_dir = tools.PROJECT_ROOT / "output" / "images" / safe
    img_dir.mkdir(parents=True, exist_ok=True)
    path = img_dir / f"{name}.png"
    path.write_bytes(data)
    return str(path)


def gen_character_ref(state: StoryState) -> dict:
    """기준 이미지 두 장(캐릭터 + 배경)을 먼저 생성한다.

    텍스트 시트만으로는 페이지마다 캐릭터·배경이 달라지므로, 이 이미지들을
    모든 페이지 삽화의 참조(images.edit)로 넣어 정체성과 세계관을 고정한다.
    이미지 생성이 꺼져 있거나 실패하면 참조 없이 진행한다(기존 방식 폴백).
    """
    quality = state.get("illust_quality", "off")
    if quality not in ("low", "medium") or not image_provider():
        return {}
    sheet = state.get("character_sheet", CHARACTER_SHEET_DEFAULT)
    theme = state.get("theme", THEME_DEFAULT)
    update: dict = {}
    try:
        data = generate_image(
            f"Character reference sheet of one single character: {sheet}. "
            f"Full body, standing, facing slightly left, gentle smile, "
            f"plain warm cream background, no scenery, no text. Style: {ILLUST_STYLE}",
            quality=quality,
        )
        if data:
            update["character_ref"] = _save_illustration(theme, "character", data)
    except Exception:
        pass  # 참조 실패 → 페이지들은 기존 텍스트 시트 방식으로 생성
    # 배경 기준: 연출 계획(plan_illustrations)의 세계관 묘사로 한 장 — 그림 이음새 앵커
    setting = state.get("setting_sheet")
    if setting:
        try:
            data = generate_image(
                f"Establishing illustration of a storybook world, no characters, no text: "
                f"{setting}. Wide view of the main location. Style: {ILLUST_STYLE}",
                quality=quality,
            )
            if data:
                update["setting_ref"] = _save_illustration(theme, "setting", data)
        except Exception:
            pass  # 배경 참조 실패 → 캐릭터 참조만으로 진행
    return update


# ── 노드 9: 페이지별 삽화 프롬프트 + 이미지 생성 (Send 병렬) ─


def gen_illust_prompt(payload: dict) -> dict:
    """finalize에서 Send로 페이지 수만큼 병렬 실행된다. payload는 페이지 1개 단위.

    캐릭터 일관성: 모든 페이지 프롬프트가 동일한 character_sheet(주인공 외형 묘사)로
    시작하므로, 이미지 생성 시 페이지마다 주인공이 달라지는 문제를 방지한다.
    illust_quality가 low/medium이고 이미지 공급자가 있으면 실제 삽화까지 그린다
    (Step 5) — 이미지 실패는 동화 완성을 막지 않는다(프롬프트만 남김).
    """
    page: Page = payload["page"]
    theme = payload["theme"]
    sheet = payload.get("character_sheet", CHARACTER_SHEET_DEFAULT)

    scene, prompt = _resolve_scene(payload, page, theme, sheet)
    entry: dict = {"page": page["page"], "prompt": prompt}
    quality = payload.get("illust_quality", "off")
    if quality in ("low", "medium") and image_provider():
        image_path, err = _make_page_image(payload, page, theme, scene, prompt, quality)
        if image_path:
            entry["image_path"] = image_path
        if err:
            entry["error"] = err
    return {"illust_prompts": [entry]}


def _make_page_image(
    payload: dict, page: Page, theme: str, scene: str, prompt: str, quality: str
) -> tuple[str | None, str | None]:
    """페이지 삽화 생성·저장 → (저장 경로, 실패 사유).

    1차: 기준 이미지 참조 생성 → 실패 시 참조 없이 일반 생성으로 1회 재시도
    (edit 엔드포인트의 일시 오류·모더레이션 거부를 다른 경로로 우회).
    그래도 실패하면 사유를 반환해 UI가 '글로만 실림'을 안내한다 —
    예전처럼 조용히 삼키면 특정 쪽만 그림이 빠진 이유를 아무도 모른다.
    """
    try:
        data = _render_page_image(payload, scene, prompt, quality)
    except Exception:
        try:
            data = generate_image(prompt, quality=quality)
        except Exception as e:
            return None, f"{type(e).__name__}: 삽화 생성 2회 실패"
    if not data:
        return None, None
    try:
        if payload.get("illust_caption", True):
            # 그림 아래 크림 띠에 페이지 글귀 합성 → 한 장짜리 그림책 페이지
            data = caption_image(data, page["text"])
        return _save_illustration(theme, f"p{page['page']}", data), None
    except Exception as e:  # 파일 저장 실패가 동화 완성을 막으면 안 됨
        return None, f"{type(e).__name__}: 삽화 저장 실패"


def _resolve_scene(payload: dict, page: Page, theme: str, sheet: str) -> tuple[str, str]:
    """(장면 묘사, 기록용 프롬프트) 결정.

    연출 계획(plan_illustrations)이 만든 장면을 우선 사용 — 배경·시간·소품 연속성.
    계획이 없을 때만 페이지 단위로 생성한다 (화풍은 고정 상수로 분리 — AI 티 방지).
    """
    scene = payload.get("illust_scene")
    if scene:
        return scene, f"{sheet} — {scene} Style: {ILLUST_STYLE}"
    if llm_provider():
        scene = call_llm(
            f"유아 동화책 삽화의 '장면 묘사'만 영어 한 문장으로 써줘.\n"
            f'반드시 이 주인공 묘사로 시작해 (한 글자도 바꾸지 말 것): "{sheet}"\n'
            f"이어서 이 페이지의 장면: {page['text']} (테마: {theme})\n"
            f"규칙: 한 가지 행동에 집중, 배경 요소는 많아야 2개, "
            f"화풍·색감·분위기 형용사(vibrant, sparkling, watercolor, cozy 등)는 절대 쓰지 마 "
            f"— 스타일은 따로 정해져 있어. 문장만 답해.",
            max_tokens=200,
        ).strip()
    else:  # mock
        scene = f"{sheet} — 장면: '{page['text']}' ({theme} 배경)"
    return scene, f"{scene} Style: {ILLUST_STYLE}"


def _render_page_image(payload: dict, scene: str, prompt: str, quality: str) -> bytes | None:
    """기준 이미지 참조(캐릭터 + 배경)로 페이지 삽화를 그린다 — 참조 없으면 일반 생성."""
    refs = []
    for key in ("character_ref", "setting_ref"):
        p_ = payload.get(key)
        if p_ and Path(p_).exists():
            refs.append(Path(p_).read_bytes())
    if not refs:
        return generate_image(prompt, quality=quality)
    guide = (
        "Using the first reference image as the exact main character "
        "(identical design and colors)"
        + (" and the second reference image as the world and setting look"
           if len(refs) > 1 else "")
        + f", draw this scene: {scene} Style: {ILLUST_STYLE}"
    )
    return edit_image_with_reference(refs, guide, quality=quality)


# ── 노드 10: 동화책 저장 (툴② 사용) ─────────────────────────
def save_storybook_node(state: StoryState) -> dict:
    title = f"{state.get('theme', '동화')} 이야기"
    path = save_storybook.invoke({
        "title": title,
        "pages": state["pages"],
        "illust_prompts": state.get("illust_prompts", []),
    })
    return {"saved_path": path}
