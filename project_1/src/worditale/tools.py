"""LangGraph 툴 — 단어 적합성 검사(툴①), 동화책 파일 저장(툴②).

check_words는 하이브리드 안전 필터:
  1차 규칙 검사 — 개수/한글/길이 + 정적 금지어 목록 (무료·즉시·예측 가능)
  2차 LLM 의미 판정 — 목록에 없는 위험 단어를 맥락으로 걸러냄 (키 있을 때만)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.tools import tool

from worditale.config import BANNED_WORDS, MAX_WORDS, MIN_WORDS
from worditale.llm import call_llm, llm_provider

# src/worditale/tools.py → parents[2] == project_1
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _llm_judge_words(words: list[str]) -> list[str]:
    """2차 필터: 정적 목록을 통과한 단어를 LLM이 의미 기준으로 판정.
    판정 실패 시 빈 목록(통과) — 1차 규칙 차단이 이미 적용됐고,
    생성 후 validate_story의 출력 안전성 검사가 한 번 더 거른다."""
    try:
        raw = call_llm(
            f"유아(3~7세) 동화의 학습 단어로 부적합한 것만 골라줘. 단어: {', '.join(words)}\n"
            f"부적합 기준: 폭력·무기·공포(귀신/좀비류)·죽음·성인 소재(술/담배/도박)·차별/혐오. "
            f"동물·자연·사물·음식·놀이 같은 일상 단어는 적합이야. 애매하면 적합으로 봐.\n"
            f'JSON으로만 답해: {{"unsafe": [{{"word": "단어", "reason": "이유 한 줄"}}]}}',
            max_tokens=300,
        )
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group())
        return [
            f"'{item['word']}'은(는) 유아에게 부적합해요 — {item.get('reason', 'AI 판정')}"
            for item in data.get("unsafe", [])
            if item.get("word") in words  # LLM이 목록 밖 단어를 지어내는 것 방지
        ]
    except Exception:
        return []


@tool
def check_words(words: list[str]) -> dict:
    """학습 단어 목록이 유아용 동화에 적합한지 하이브리드로 검사한다.
    1차: 개수(5~10개)/한글/길이(1~5자) 규칙 + 정적 금지어 목록으로 즉시 차단.
    2차: 1차를 통과하면 LLM이 의미 기준(폭력·공포·성인 소재 등)으로 판정.
    {"ok": bool, "problems": [문제 설명]} 형태로 반환한다."""
    problems: list[str] = []
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        problems.append(f"단어 개수는 {MIN_WORDS}~{MAX_WORDS}개여야 합니다 (현재 {len(words)}개)")
    for w in words:
        if w in BANNED_WORDS:
            problems.append(f"'{w}'은(는) 유아 동화에 부적합한 단어입니다")
        elif not re.fullmatch(r"[가-힣]{1,5}", w):
            problems.append(f"'{w}'은(는) 1~5자의 한글 단어가 아닙니다")

    # 2차 LLM 판정은 1차를 전부 통과했을 때만 (명백한 차단에 비용·지연을 쓰지 않음)
    if not problems and llm_provider():
        problems += _llm_judge_words(words)

    return {"ok": not problems, "problems": problems}


@tool
def save_storybook(title: str, pages: list[dict], illust_prompts: list[dict]) -> str:
    """완성된 동화(페이지 텍스트 + 페이지별 삽화 프롬프트)를
    output/<제목>.md 마크다운 파일로 저장하고 저장 경로를 반환한다."""
    out_dir = PROJECT_ROOT / "output"
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
