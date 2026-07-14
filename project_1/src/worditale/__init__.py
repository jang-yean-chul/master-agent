"""
WordiTale (워디테일) — 유아 단어 학습 동화 생성 에이전트

아키텍처: 워크플로우 3패턴 조합
  · 프롬프트 체이닝: 기획 → 작성 → 검증(게이트) → 마무리
  · Orchestrator-Workers: plan_story(오케스트레이터)가 페이지 수·단어 배치·
    페이지별 브리프를 동적으로 계획 → 페이지 워커들이 병렬 작성
  · 병렬 처리: 페이지 작성 워커 ×N, 삽화 프롬프트 ×N (Send API)

모듈 구성:
  config.py  비즈니스 규칙 상수·주인공 기본값
  state.py   그래프 State(TypedDict) + 리듀서
  llm.py     LLM 클라이언트 (OpenAI/Claude/mock 자동 선택)
  tools.py   툴① check_words · 툴② save_storybook
  nodes.py   노드 함수 (오케스트레이터/워커/검증/삽화/저장)
  graph.py   라우팅 + 그래프 조립 (+ MemorySaver 체크포인터)
  voice_store.py  가족 목소리 mp3 샘플 저장소 (TTS 준비)

실행: python -m worditale  (CLI 데모)
"""
from worditale.config import (
    HERO_DEFAULT,
    MAX_CHARS_PER_PAGE,
    MAX_PAGES,
    MAX_RETRIES,
    MAX_WORDS,
    MIN_PAGES,
    MIN_WORDS,
    TODDLER_MAX_AGE,
    hero_name,
)
from worditale.graph import graph
from worditale.llm import call_llm, llm_provider
from worditale.tools import check_words, save_storybook

__all__ = [
    "HERO_DEFAULT", "MAX_CHARS_PER_PAGE", "MAX_PAGES", "MAX_RETRIES", "MAX_WORDS",
    "MIN_PAGES", "MIN_WORDS", "TODDLER_MAX_AGE",
    "call_llm", "check_words", "graph", "hero_name", "llm_provider", "save_storybook",
]
