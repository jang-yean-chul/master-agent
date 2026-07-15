"""그래프 end-to-end 테스트 (mock 모드) — 배선·라우팅·재시도 루프·메모리.

LLM 없이 규칙 기반으로 그래프 전체를 돌려서, 노드 연결과 상태 흐름이
설계대로 동작하는지 결정적으로 검증한다.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from worditale.config import MAX_PAGES, MIN_PAGES
from worditale.graph import graph

WORDS = ["사과", "나비", "구름", "바람", "노래"]


def _config() -> dict:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def _run(config=None, **inputs) -> dict:
    inputs.setdefault("target_words", WORDS)
    inputs.setdefault("child_age", 4)
    inputs.setdefault("theme", "숲속 모험")
    return graph.invoke(inputs, config or _config())


class TestHappyPath:
    def test_full_pipeline(self, isolated_output):
        result = _run()

        assert result["status"] == "ok"
        assert MIN_PAGES <= len(result["pages"]) <= MAX_PAGES

        full_text = " ".join(p["text"] for p in result["pages"])
        for w in WORDS:
            assert w in full_text  # 학습 단어 전부 본문에 등장

        # 페이지마다 삽화 프롬프트 1개, 저장 파일 생성
        assert len(result["illust_prompts"]) == len(result["pages"])
        assert Path(result["saved_path"]).exists()

    def test_pages_are_ordered(self):
        result = _run()
        assert [p["page"] for p in result["pages"]] == \
            list(range(1, len(result["pages"]) + 1))


class TestRejectRoute:
    def test_banned_word_rejects_without_generating(self):
        result = _run(target_words=["사과", "나비", "구름", "바람", "칼"])
        assert result["status"] == "rejected"
        assert result["issues"]
        assert "story_plan" not in result  # plan_story까지 가지 않아야 함

    def test_wrong_count_rejects(self):
        result = _run(target_words=["사과", "나비"])
        assert result["status"] == "rejected"


class TestRetryLoop:
    def test_demo_failure_recovers_via_rewrite(self):
        """첫 시도에 단어를 일부러 누락 → 검증 실패 → 재작성 → 최종 성공."""
        result = _run(demo_fail_first=True)
        assert result["retry_count"] == 1   # 정확히 1회 재작성
        assert result["status"] == "ok"
        full_text = " ".join(p["text"] for p in result["pages"])
        assert WORDS[-1] in full_text        # 누락됐던 단어가 재작성으로 복구


class TestAgeRouting:
    def test_toddler_worker_used_for_age_2(self):
        result = _run(child_age=2)
        assert result["status"] == "ok"
        assert "코~ 잘 자요" in result["pages"][-1]["text"]  # 영아용 워커의 맺음말

    def test_standard_worker_used_for_age_5(self):
        result = _run(child_age=5)
        assert "잠들었답니다" in result["pages"][-1]["text"]  # 표준 워커의 맺음말


class TestThreadMemory:
    def test_learned_words_accumulate_across_stories(self):
        config = _config()
        _run(config)
        second = ["기차", "무지개", "딸기", "피아노", "우산"]
        result = _run(config, target_words=second)

        assert set(result["learned_words"]) == set(WORDS) | set(second)
        # 두 번째 동화 기획에 복습 단어(이전에 배운 단어)가 등장
        assert "지난번에 배운" in result["story_plan"]

    def test_separate_threads_do_not_share_memory(self):
        _run()
        result = _run()  # 새 thread
        assert set(result["learned_words"]) == set(WORDS)
