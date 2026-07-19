"""WordiTale 비즈니스 규칙 상수 · 주인공 기본값."""
from __future__ import annotations

# ── 비즈니스 규칙 ─────────────────────────────────────────────
MIN_WORDS, MAX_WORDS = 5, 10        # 학습 단어 개수
MIN_PAGES, MAX_PAGES = 5, 8         # 동화 페이지 수
MAX_CHARS_PER_PAGE = 100            # 페이지당 최대 글자 수 (유아용 간단 텍스트)
MAX_RETRIES = 2                     # 재작성 루프 상한 (무한 루프 방지)
TODDLER_MAX_AGE = 3                 # 이 나이 이하면 영아용 작문 스타일

# 유아 동화에 넣을 수 없는 단어 — 1차 정적 차단 목록 (명백한 것만, 무료·즉시)
# 목록에 없는 위험 단어(예: 좀비)는 2차 LLM 의미 판정이 걸러낸다 (tools.check_words)
BANNED_WORDS = {
    # 무기·폭력
    "칼", "식칼", "총", "권총", "폭탄", "전쟁", "무기", "흉기", "폭력",
    # 성인 소재
    "술", "소주", "맥주", "와인", "담배", "마약", "도박",
    # 죽음·상해
    "죽음", "살인", "자살", "시체", "피",
    # 공포
    "귀신", "유령", "악마", "저주", "지옥",
    # 범죄·괴롭힘
    "유괴", "납치", "감옥", "왕따",
}

# ── 텍스트 생성 모델 ─────────────────────────────────────────
# gpt-4o-mini는 한국어 서사가 약해 스토리가 단어 나열형으로 나옴 (2026-07-18 교체).
TEXT_MODEL_OPENAI = "gpt-4.1"
TEXT_MODEL_ANTHROPIC = "claude-sonnet-4-5"

# ── 삽화 화풍 (고정 아트 디렉션) ─────────────────────────────
# "pastel watercolor, bright and cozy" 같은 범용 스타일은 AI 기본값이라 티가 남.
# 플랫 그림책풍은 실전에서 기괴한 편차가 커서(외곽선 스타일의 uncanny 위험 +
# 인쇄 아티팩트 문구) 손맛 수채화로 교체 (2026-07-18, 사용자 확정).
# 장면 묘사와 분리해 모든 페이지 프롬프트 끝에 동일하게 붙인다 (화풍 일관성).
ILLUST_STYLE = (
    "traditional watercolor painted on rough cold-press paper: visible paper texture, "
    "uneven pigment blooms and granulation, loose wet-on-wet washes, faint pencil "
    "underdrawing showing through, warm muted low-saturation palette, handmade "
    "imperfections, absolutely no digital smoothness or airbrush gradients"
)

# ── 기본값 ───────────────────────────────────────────────────
THEME_DEFAULT = "숲속 모험"

# ── 주인공 (캐릭터 일관성 기준) ──────────────────────────────
HERO_DEFAULT = "아기 토끼 토토"
CHARACTER_SHEET_DEFAULT = (
    "the same main character on every page: a cute baby rabbit named Toto "
    "with soft cream fur, round pink cheeks, and a tiny yellow scarf"
)


def hero_name(hero: str) -> str:
    """주인공 문구에서 부를 이름만 추출 ('아기 토끼 토토' → '토토')."""
    return hero.split()[-1] if hero.split() else hero
