"""LLM 클라이언트 — OpenAI ↔ Claude 겸용, 키 없으면 mock 신호(None).

이후 이미지 생성(Step 5)·TTS(Step 6) 클라이언트도 이 모듈에 추가한다.
"""
from __future__ import annotations

import os


def llm_provider() -> str | None:
    """사용할 LLM 공급자. 키가 없으면 None → 호출부는 mock 로직으로 동작."""
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def call_llm(prompt: str, max_tokens: int = 1500) -> str:
    provider = llm_provider()
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
