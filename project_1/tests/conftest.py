"""공통 픽스처 — src 경로 등록 + mock 모드 강제(API 키 제거)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    """모든 테스트를 mock 모드로 실행 — 실수로 실제 API를 호출해 비용이 나가는 것 방지.
    실제 LLM 품질 평가는 pytest가 아니라 evals/run_eval.py 담당."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def isolated_output(monkeypatch, tmp_path):
    """save_storybook이 실제 output/ 대신 임시 폴더에 저장하게 격리."""
    from worditale import tools

    monkeypatch.setattr(tools, "PROJECT_ROOT", tmp_path)
    return tmp_path
