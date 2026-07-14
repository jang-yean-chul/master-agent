"""CLI 데모 — python -m worditale

시나리오 3종: ① 재작성 루프 ② 나이 분기 + 메모리(복습 단어) ③ 부적합 단어 거절
"""
from __future__ import annotations

from pathlib import Path

from worditale.graph import graph
from worditale.llm import llm_provider


def _print_story(label: str, result: dict) -> None:
    print(f"--- {label} ---")
    print(f"[줄거리] {result['story_plan']}\n")
    for p in result["pages"]:
        print(f"  p{p['page']}. {p['text']}")
    print(f"\n[검증] 재작성 {result['retry_count']}회, 최종 상태: {result['status']}")
    if result.get("issues"):
        print(f"[남은 문제] {result['issues']}")
    print(f"[삽화 프롬프트] {len(result.get('illust_prompts', []))}개 병렬 생성")
    for ip in sorted(result.get("illust_prompts", []), key=lambda x: x["page"])[:2]:
        print(f"  p{ip['page']}: {ip['prompt']}")
    print(f"[저장] {result.get('saved_path')}")
    print(f"[메모리] 지금까지 배운 단어: {result.get('learned_words')}\n")


def main() -> None:
    try:
        import dotenv

        dotenv.load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except ImportError:
        pass

    mode = llm_provider() or "mock"
    print(f"=== WordiTale 실행 (LLM 모드: {mode}) ===\n")

    # 아이별 세션: 같은 thread_id면 배운 단어가 누적된다 (메모리)
    yeonu = {"configurable": {"thread_id": "child-yeonu"}}

    # ① 4세 표준 스타일 + 검증 실패 → 재작성 루프 시연
    r1 = graph.invoke({
        "target_words": ["사과", "구름", "나비", "바람", "무지개", "달팽이"],
        "child_age": 4,
        "theme": "숲속 모험",
        "demo_fail_first": True,
    }, yeonu)
    _print_story("동화 1: 4세 · 숲속 모험 (재작성 루프 시연)", r1)

    # ② 같은 아이, 3세 영아 스타일 → 나이 분기 + 메모리(배운 단어 누적) 시연
    r2 = graph.invoke({
        "target_words": ["물고기", "거북이", "소라", "파도", "진주"],
        "child_age": 3,
        "theme": "바닷속 여행",
        "demo_fail_first": False,
    }, yeonu)
    _print_story("동화 2: 3세 · 바닷속 여행 (영아 스타일 + 복습 단어)", r2)

    # ③ 부적합 단어 포함 → check_words 툴이 거절하는 분기 시연
    r3 = graph.invoke({
        "target_words": ["사과", "칼", "나비", "바람", "구름"],
        "child_age": 4,
        "theme": "숲속 모험",
    }, {"configurable": {"thread_id": "reject-demo"}})
    print("--- 동화 3: 부적합 단어 → 입력 거절 시연 ---")
    print(f"[상태] {r3['status']}")
    print(f"[사유] {r3['issues']}")


if __name__ == "__main__":
    main()
