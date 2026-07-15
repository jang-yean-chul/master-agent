"""AI-as-judge 오프라인 품질 평가.

pytest(결정적 로직 검증)와 역할이 다르다:
  - pytest  : 규칙·배선·폴백이 깨졌는지 → 매 커밋, 무료, mock 모드
  - 이 스크립트: 실제 LLM 출력의 '품질'이 좋은지 → 프롬프트 수정 시 수동 실행, 유료

고정 케이스(cases.py)로 동화를 생성한 뒤,
  1) 결정적 지표: 단어 커버리지·페이지 수·글자 수 (validate와 동일 기준)
  2) judge LLM: 항목별 rubric 채점 (1~5점 + 근거)
을 수집해 콘솔 요약 + evals/results/<시각>.md 리포트를 남긴다.

실행:  python evals/run_eval.py [케이스id ...]   (id 생략 시 전체)
필요:  .env에 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Windows 콘솔(cp949)에서 한글·이모지 출력이 깨지거나 크래시하는 것 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dotenv

dotenv.load_dotenv(PROJECT_ROOT / ".env")

from worditale.config import HERO_DEFAULT, MAX_CHARS_PER_PAGE, MAX_PAGES, MIN_PAGES, hero_name  # noqa: E402
from worditale.graph import graph  # noqa: E402
from worditale.llm import call_llm, llm_provider  # noqa: E402

from cases import EVAL_CASES  # noqa: E402

RUBRIC = {
    "narrative_flow": "페이지 간 사건이 자연스럽게 이어지는가 (내용 중복·비약 없음)",
    "word_naturalness": "학습 단어가 억지스럽지 않게 문장에 녹아 있는가",
    "style_consistency": "해요체 문체와 연령에 맞는 문장 길이가 전체적으로 일관적인가",
    "age_fit": "소재·감정 톤이 해당 연령에게 적합하고 안전한가 (무섭거나 어두운 요소 없음)",
    "character_consistency": "주인공을 정해진 이름으로만 일관되게 지칭하는가",
}
PASS_THRESHOLD = 4.0  # 항목 평균이 이 미만이면 케이스 FAIL로 표시


# ── 결정적 지표 (judge 없이 코드로 측정) ─────────────────────
def deterministic_metrics(pages: list[dict], words: list[str]) -> dict:
    full_text = " ".join(p["text"] for p in pages)
    missing = [w for w in words if w not in full_text]
    overlong = [p["page"] for p in pages if len(p["text"]) > MAX_CHARS_PER_PAGE]
    return {
        "page_count": len(pages),
        "page_count_ok": MIN_PAGES <= len(pages) <= MAX_PAGES,
        "word_coverage": f"{len(words) - len(missing)}/{len(words)}",
        "missing_words": missing,
        "overlong_pages": overlong,
    }


# ── judge LLM 채점 ───────────────────────────────────────────
def judge_story(case: dict, pages: list[dict]) -> dict:
    inputs = case["inputs"]
    hero = inputs.get("hero", HERO_DEFAULT)
    story = "\n".join(f"{p['page']}페이지: {p['text']}" for p in pages)
    rubric_lines = "\n".join(f"- {k}: {v}" for k, v in RUBRIC.items())

    raw = call_llm(
        f"너는 유아 동화 품질 평가 전문가야. 아래 동화를 rubric대로 엄격하게 채점해줘.\n\n"
        f"[조건] 대상 연령: {inputs['child_age']}세 / "
        f"학습 단어: {', '.join(inputs['target_words'])} / "
        f"주인공: '{hero}' — 본문에서 이름 '{hero_name(hero)}'(으)로만 지칭해야 함 / "
        f"테마: {inputs['theme']}\n\n"
        f"[동화 본문]\n{story}\n\n"
        f"[채점 항목 — 각 1~5점, 5가 최고. 근거는 본문에서 인용해 한 줄로]\n{rubric_lines}\n\n"
        f"JSON으로만 답해:\n"
        f'{{"scores": {{{", ".join(f_json_slot(k) for k in RUBRIC)}}}, '
        f'"overall_comment": "총평 한두 문장"}}',
        max_tokens=800,
    )
    return json.loads(re.search(r"\{.*\}", raw, re.S).group())


def f_json_slot(key: str) -> str:
    return f'"{key}": {{"score": 점수, "reason": "근거"}}'


# ── 케이스 1건 실행 ──────────────────────────────────────────
def run_case(case: dict) -> dict:
    config = {"configurable": {"thread_id": f"eval-{case['id']}-{uuid.uuid4()}"}}
    result = graph.invoke(dict(case["inputs"]), config)

    record: dict = {"case": case, "status": result.get("status")}
    if result.get("status") != "ok":
        record["issues"] = result.get("issues", [])
        return record

    pages = result["pages"]
    record["pages"] = pages
    record["retry_count"] = result.get("retry_count", 0)
    record["metrics"] = deterministic_metrics(pages, case["inputs"]["target_words"])
    try:
        record["judge"] = judge_story(case, pages)
        scores = [int(v["score"]) for v in record["judge"]["scores"].values()]
        record["avg_score"] = round(sum(scores) / len(scores), 2)
    except Exception as e:  # judge 응답 파싱 실패 — 케이스는 남기고 표시만
        record["judge_error"] = f"{type(e).__name__}: {e}"
    return record


# ── 리포트 ───────────────────────────────────────────────────
def write_report(records: list[dict], path: Path) -> None:
    lines = [f"# WordiTale 품질 평가 리포트 — {datetime.datetime.now():%Y-%m-%d %H:%M}",
             "", f"- LLM 공급자: {llm_provider()}", f"- 합격 기준: 평균 {PASS_THRESHOLD}점 이상", ""]

    lines += ["| 케이스 | 상태 | 평균 | " + " | ".join(RUBRIC) + " | 커버리지 | 재작성 |",
              "|---|---|---|" + "---|" * len(RUBRIC) + "---|---|"]
    for r in records:
        case_id = r["case"]["id"]
        if r["status"] != "ok":
            lines.append(f"| {case_id} | {r['status']} | — |" + " — |" * len(RUBRIC) + " — | — |")
            continue
        judge = r.get("judge", {}).get("scores", {})
        cells = " | ".join(str(judge.get(k, {}).get("score", "?")) for k in RUBRIC)
        avg = r.get("avg_score", "?")
        verdict = "✅" if isinstance(avg, float) and avg >= PASS_THRESHOLD else "⚠️"
        lines.append(f"| {case_id} | {verdict} | {avg} | {cells} | "
                     f"{r['metrics']['word_coverage']} | {r['retry_count']}회 |")
    lines.append("")

    for r in records:
        case = r["case"]
        lines += [f"## {case['id']} — {case['focus']}", ""]
        if r["status"] != "ok":
            lines += [f"**상태: {r['status']}** — {'; '.join(r.get('issues', []))}", ""]
            continue
        m = r["metrics"]
        if m["missing_words"] or m["overlong_pages"] or not m["page_count_ok"]:
            lines.append(f"- ⚠️ 결정적 지표 위반: 누락 {m['missing_words']}, "
                         f"초과 페이지 {m['overlong_pages']}, 페이지 수 {m['page_count']}")
        if "judge" in r:
            for k, v in r["judge"]["scores"].items():
                lines.append(f"- **{k}: {v['score']}점** — {v['reason']}")
            lines += ["", f"> 총평: {r['judge'].get('overall_comment', '')}", ""]
        else:
            lines += [f"- judge 채점 실패: {r.get('judge_error')}", ""]
        lines += ["<details><summary>생성된 본문</summary>", ""]
        lines += [f"{p['page']}p. {p['text']}  " for p in r["pages"]]
        lines += ["", "</details>", ""]

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not llm_provider():
        print("API 키가 없습니다 (.env의 ANTHROPIC_API_KEY / OPENAI_API_KEY).")
        print("AI-as-judge 평가는 실제 LLM 출력이 필요해요. 로직 검증은 pytest를 쓰세요.")
        return 1

    wanted = set(sys.argv[1:])
    cases = [c for c in EVAL_CASES if not wanted or c["id"] in wanted]
    if not cases:
        print(f"해당 id의 케이스가 없습니다: {', '.join(wanted)}")
        return 1

    records = []
    for case in cases:
        print(f"▶ {case['id']} ({case['focus']}) ...", flush=True)
        r = run_case(case)
        records.append(r)
        if r["status"] != "ok":
            print(f"  상태: {r['status']} — {'; '.join(r.get('issues', []))}")
        elif "avg_score" in r:
            flag = "✅" if r["avg_score"] >= PASS_THRESHOLD else "⚠️"
            print(f"  {flag} 평균 {r['avg_score']}점 · 커버리지 {r['metrics']['word_coverage']}"
                  f" · 재작성 {r['retry_count']}회")
        else:
            print(f"  judge 채점 실패: {r.get('judge_error')}")

    out_dir = PROJECT_ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / f"eval_{datetime.datetime.now():%Y%m%d_%H%M%S}.md"
    write_report(records, report)
    print(f"\n리포트 저장: {report}")

    avgs = [r["avg_score"] for r in records if "avg_score" in r]
    ok = avgs and all(a >= PASS_THRESHOLD for a in avgs) \
        and all(r["status"] == "ok" for r in records)
    print("전체 결과:", "✅ PASS" if ok else "⚠️ 확인 필요")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
