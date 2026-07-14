"""LangGraph 툴 — 단어 적합성 검사(툴①), 동화책 파일 저장(툴②)."""
from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

from worditale.config import BANNED_WORDS, MAX_WORDS, MIN_WORDS

# src/worditale/tools.py → parents[2] == project_1
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
