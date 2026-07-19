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


def image_provider() -> str | None:
    """이미지 생성 공급자. 현재 OpenAI(gpt-image-1)만 지원 — 키 없으면 None."""
    return "openai" if os.environ.get("OPENAI_API_KEY") else None


def generate_image(prompt: str, quality: str = "low") -> bytes | None:
    """삽화 1장을 생성해 PNG 바이트로 반환. 키가 없으면 None(mock).

    quality: "low"(빠른 테스트용) | "medium"(최종 출력용) — gpt-image-1 기준.
    실패는 호출부에서 처리하도록 예외를 그대로 올린다.
    """
    if not image_provider():
        return None
    import base64

    from openai import OpenAI

    resp = OpenAI().images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        quality=quality,
        n=1,
    )
    return base64.b64decode(resp.data[0].b64_json)


def edit_image_with_reference(
    reference_pngs: bytes | list[bytes], prompt: str, quality: str = "low"
) -> bytes | None:
    """기준 이미지(들)를 참조로 새 장면을 생성 (gpt-image-1 images.edit).

    텍스트 시트만으로는 페이지마다 캐릭터·배경이 달라지므로,
    기준 이미지(캐릭터, 필요 시 배경까지)를 넣어 정체성을 고정한다.
    """
    if not image_provider():
        return None
    import base64
    import io

    from openai import OpenAI

    if isinstance(reference_pngs, bytes):
        reference_pngs = [reference_pngs]
    files = []
    for i, png in enumerate(reference_pngs):
        f = io.BytesIO(png)
        f.name = f"reference{i}.png"  # SDK가 MIME 추정에 파일명을 사용
        files.append(f)
    kwargs = {
        "model": "gpt-image-1",
        "image": files if len(files) > 1 else files[0],
        "prompt": prompt,
        "size": "1024x1024",
        "quality": quality,
        "n": 1,
    }
    client = OpenAI()
    try:
        # input_fidelity=high: 참조 이미지의 캐릭터 디테일 보존 강화 (지원 SDK에서만)
        resp = client.images.edit(**kwargs, input_fidelity="high")
    except TypeError:
        resp = client.images.edit(**kwargs)
    return base64.b64decode(resp.data[0].b64_json)


def call_llm(prompt: str, max_tokens: int = 1500) -> str:
    from worditale.config import TEXT_MODEL_ANTHROPIC, TEXT_MODEL_OPENAI

    provider = llm_provider()
    if provider == "openai":
        from openai import OpenAI  # pip install openai

        resp = OpenAI().chat.completions.create(
            model=TEXT_MODEL_OPENAI,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
    import anthropic  # pip install anthropic

    resp = anthropic.Anthropic().messages.create(
        model=TEXT_MODEL_ANTHROPIC,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text
