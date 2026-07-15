"""
WordiTale (워디테일) — Streamlit 대화형 UI

채팅으로 학습 단어 → 아이 나이 → 테마를 차례로 받아 동화를 생성한다.
생성 중에는 LangGraph 노드/툴 실행 과정을 실시간으로 시각화하고,
사이드바에서 아이별 메모리(배운 단어)와 에이전트 그래프 구조를 보여준다.

실행: streamlit run app.py
"""
from __future__ import annotations

import os
import re
import sys

import dotenv

dotenv.load_dotenv()

import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from worditale import (  # noqa: E402
    HERO_DEFAULT,
    MAX_WORDS,
    MIN_WORDS,
    check_words,
    graph,
    llm_provider,
)
from worditale import voice_store  # noqa: E402

st.set_page_config(page_title="WordiTale", page_icon="🐰", layout="wide")

# ── 노드 실행 시각화용 라벨 ──────────────────────────────────
NODE_LABELS = {
    "check_words": "🔧 툴① check_words — 단어 적합성 검사 (규칙 + AI 의미 판정)",
    "reject_input": "🚫 reject_input — 부적합 입력 거절",
    "plan_story": "📝 plan_story — 오케스트레이터: 줄거리 + 페이지별 브리프 설계",
    "finalize": "✅ finalize — 상태 확정 + 배운 단어 메모리 누적",
    "save_storybook": "💾 툴② save_storybook — 동화책 파일 저장",
}
PAGE_WORKERS = {
    "write_page_toddler": "영아용(≤3세) 의성어 스타일",
    "write_page_standard": "표준(≥4세) 스토리 스타일",
}

GREETING = (
    f"안녕하세요! 저는 동화 요정 **워디**예요. 🐰\n\n"
    f"처음이시라면 위의 **💡 이용 가이드**를 먼저 펼쳐보세요!\n\n"
    f"준비되셨으면, 아이가 배울 **단어 {MIN_WORDS}~{MAX_WORDS}개**를 쉼표로 구분해 입력해주세요.\n\n"
    f"예) `사과, 구름, 나비, 바람, 무지개`"
)

GUIDE = f"""
##### 이렇게 입력하면 더 좋은 동화가 나와요!

**1. 단어 고르기** 🍎
- **{MIN_WORDS}~{MAX_WORDS}개**, 아이가 눈으로 보고 가리킬 수 있는 **구체적인 사물·자연·동물 명사**가 좋아요 → `사과, 구름, 나비` ⭕ / `행복, 효율` ❌
- 서로 어울리는 단어끼리 묶으면 이야기가 자연스러워요 → 바다 세트: `물고기, 파도, 소라` / 숲 세트: `나무, 다람쥐, 도토리`
- 무섭거나 위험한 단어(칼, 총 등)는 자동으로 거절돼요 — 금지어 목록 + AI 의미 판단의 이중 필터

**2. 나이 입력** 👶
- **3세 이하**: 의성어 중심의 아주 짧은 문장으로 써요 → "나비를 봐요. 팔랑팔랑!"
- **4세 이상**: 이야기가 있는 문장으로 써요 → "토토는 나비를 따라 꽃밭으로 갔어요."

**3. 테마 정하기** 🗺️
- **장소 + 활동**으로 구체적으로 적으면 좋아요 → `숲속 모험`, `바닷속 여행`, `우주 소풍`, `할머니 댁 가는 길`
- 배우는 단어들과 어울리는 테마면 단어가 더 자연스럽게 녹아들어요

**4. 주인공 바꾸기 (왼쪽 사이드바)** 🐰
- 기본 주인공은 `{HERO_DEFAULT}`예요. `호기심 많은 아기 곰 보리`처럼 **성격 + 동물/사람 + 이름** 형식으로 바꿔보세요
- 아이가 좋아하는 동물이나 아이 애칭을 이름으로 쓰면 몰입도가 올라가요. 모든 페이지와 그림에서 같은 모습으로 유지됩니다

**5. 배운 단어 복습** 🔁
- 사이드바의 **아이 이름**이 같으면 지난 동화의 단어를 기억했다가 다음 동화에 살짝 다시 등장시켜요
- 형제자매는 이름을 다르게 입력하면 따로 기억해요

**6. 가족 목소리 등록** 🎙️
- 아래 "우리 가족 목소리 등록"에서 엄마·아빠·할아버지·할머니 목소리를 **약 2분짜리 mp3 2개**씩 올려두세요
- 나중에 그 목소리로 동화를 읽어주는 기능에 쓰여요 (조용한 방에서, 아이에게 읽어주듯 또박또박!)
"""


# ── 세션 상태 초기화 ─────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": GREETING}]
if "stage" not in st.session_state:
    st.session_state["stage"] = "words"   # words → age → theme → (생성) → words
if "pending" not in st.session_state:
    st.session_state["pending"] = {}      # 수집 중인 입력 {words, age}


def say(content: str, **extra) -> None:
    st.session_state["messages"].append({"role": "assistant", "content": content, **extra})


# ── 사이드바: 아이별 메모리 + 실행 모드 ──────────────────────
with st.sidebar:
    st.header("👶 아이 설정")
    child_name = st.text_input("아이 이름 (이름별로 배운 단어가 기억돼요)", value="우리아이")
    hero = st.text_input(
        "주인공 캐릭터 (성격 + 동물/사람 + 이름)",
        value=HERO_DEFAULT,
        help="모든 페이지와 삽화에서 같은 모습으로 유지돼요. 예) 호기심 많은 아기 곰 보리",
    )
    config = {"configurable": {"thread_id": f"child-{child_name}"}}

    snapshot = graph.get_state(config)
    learned = snapshot.values.get("learned_words", []) if snapshot.values else []
    st.metric("지금까지 배운 단어", f"{len(learned)}개")
    if learned:
        st.caption(", ".join(learned))

    st.divider()
    mode = llm_provider() or "mock"
    st.caption(f"LLM 모드: **{mode}**" + (" (키 없이 규칙 기반 데모)" if mode == "mock" else ""))

    if st.button("💬 대화 초기화"):
        st.session_state["messages"] = [{"role": "assistant", "content": GREETING}]
        st.session_state["stage"] = "words"
        st.session_state["pending"] = {}
        st.rerun()


# ── 헤더 + 그래프 구조 시각화 ────────────────────────────────
st.title("🐰 WordiTale — 우리 아이 맞춤 동화")
st.caption("배울 단어로 만드는 5~8페이지 맞춤 동화 · LangGraph 에이전트")

# 처음 방문(대화 시작 전)이면 가이드를 펼쳐서 보여준다
with st.expander("💡 이용 가이드 — 이렇게 입력하면 좋아요", expanded=len(st.session_state["messages"]) <= 1):
    st.markdown(GUIDE)

# ── 가족 목소리 등록 (부모 음성 TTS 준비) ────────────────────
if "upload_nonce" not in st.session_state:
    st.session_state["upload_nonce"] = 0

with st.expander("🎙️ 우리 가족 목소리 등록 — 동화 낭독 준비"):
    st.markdown(
        f"""나중에 **등록한 목소리로 동화를 읽어주는** 기능에 쓰여요. 역할별로 **약 2분짜리 mp3 녹음 {voice_store.MAX_SAMPLES_PER_ROLE}개**를 올려주세요.

**녹음 팁** 🎧 조용한 방에서 · 휴대폰을 입에서 한 뼘 거리에 두고 · 아이에게 동화를 읽어주듯 또박또박 · 평소 말투로 자연스럽게
(허용 길이: {voice_store.MIN_SECONDS}초 ~ {voice_store.MAX_SECONDS // 60}분 · 권장 {voice_store.TARGET_SECONDS // 60}분)"""
    )

    # 직전 rerun에서 저장한 결과 메시지 표시
    for ok, text in st.session_state.pop("voice_msgs", []):
        (st.success if ok else st.error)(text)

    summary = voice_store.roles_summary()
    cols = st.columns(len(voice_store.VOICE_ROLES))
    for col, (r, n) in zip(cols, summary.items()):
        if n >= voice_store.MAX_SAMPLES_PER_ROLE:
            icon = "✅"
        elif n:
            icon = "🟡"
        else:
            icon = "⬜"
        col.markdown(f"{icon} **{r}** {n}/{voice_store.MAX_SAMPLES_PER_ROLE}")

    role = st.radio("누구의 목소리인가요?", voice_store.VOICE_ROLES, horizontal=True)

    for sample in voice_store.list_samples(role):
        c1, c2, c3 = st.columns([5, 2, 1])
        c1.audio(str(sample["path"]), format="audio/mp3")
        c2.caption(f"{sample['seconds'] / 60:.1f}분")
        if c3.button("🗑️ 삭제", key=f"del-{sample['path'].name}-{role}"):
            voice_store.delete_sample(role, sample["path"])
            st.rerun()

    uploads = st.file_uploader(
        f"{role} 목소리 mp3 업로드 (여러 개 선택 가능)",
        type=["mp3"],
        accept_multiple_files=True,
        key=f"voice-upload-{st.session_state['upload_nonce']}",
    )
    if uploads and st.button("💾 업로드한 목소리 저장", type="primary"):
        results = []
        for f in uploads:
            ok, msg = voice_store.save_sample(role, f.getvalue())
            results.append((ok, f"{f.name}: {msg}"))
        st.session_state["voice_msgs"] = results
        st.session_state["upload_nonce"] += 1  # 업로더 초기화 (중복 저장 방지)
        st.rerun()

@st.cache_resource
def graph_html() -> Path:
    """그래프 구조를 mermaid로 그리는 HTML을 임시 파일로 생성 (st.iframe용)."""
    mermaid_src = graph.get_graph().draw_mermaid()
    html = f"""<!doctype html><meta charset="utf-8">
<pre class="mermaid" style="background: transparent; text-align: center;">{mermaid_src}</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";
  mermaid.initialize({{ startOnLoad: true, theme: "neutral" }});
</script>"""
    path = Path(tempfile.gettempdir()) / "worditale_graph.html"
    path.write_text(html, encoding="utf-8")
    return path


with st.expander("🗺️ 에이전트 그래프 구조 보기"):
    st.iframe(graph_html(), height=560)


# ── 지난 대화 그리기 ─────────────────────────────────────────
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("trace"):
            with st.expander("🛠️ 에이전트 실행 과정"):
                for line in msg["trace"]:
                    st.markdown(f"- {line}")
        if msg.get("illust"):
            with st.expander("🎨 페이지별 삽화 프롬프트"):
                for ip in sorted(msg["illust"], key=lambda x: x["page"]):
                    st.markdown(f"**p{ip['page']}** — {ip['prompt']}")


# ── 동화 생성 (노드 실행 실시간 시각화) ──────────────────────
def run_generation(words: list[str], age: int, theme: str) -> tuple[dict, list[str]]:
    trace: list[str] = []
    illust_count = 0
    retry_seen = 0
    worker_counts: dict[str, int] = {}

    def emit(line: str) -> None:
        st.write(line)
        trace.append(line)

    with st.status("🪄 동화를 만드는 중...", expanded=True) as status:
        inputs = {"target_words": words, "child_age": age, "theme": theme,
                  "hero": hero, "demo_fail_first": False}
        for chunk in graph.stream(inputs, config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "gen_illust_prompt":
                    illust_count += 1
                    continue  # 병렬 실행이라 개수만 세고, 완료 시 한 줄로 표시
                if node in PAGE_WORKERS:
                    worker_counts[node] = worker_counts.get(node, 0) + 1
                    continue  # 페이지 워커도 병렬 — validate 직전에 한 줄로 표시
                if node == "validate_story":
                    for wn, cnt in worker_counts.items():
                        emit(f"⚡ {wn} ×{cnt} — 페이지 병렬 작성 ({PAGE_WORKERS[wn]})")
                    worker_counts = {}
                    issues = (update or {}).get("issues") or []
                    if issues:
                        retry_seen += 1
                        line = f"🔍 validate_story — 문제 발견({'; '.join(issues)}) → 재작성 {retry_seen}회차"
                    else:
                        line = "🔍 validate_story — 검증 통과"
                elif node == "save_storybook":
                    if illust_count:
                        emit(f"⚡ gen_illust_prompt ×{illust_count} — 삽화 프롬프트 병렬 생성 완료")
                    line = NODE_LABELS[node]
                else:
                    line = NODE_LABELS.get(node, f"⚙️ {node}")
                emit(line)
        status.update(label="✨ 완성!", state="complete", expanded=False)

    return graph.get_state(config).values, trace


def story_markdown(values: dict) -> str:
    lines = [f"### 📖 {values.get('theme', '동화')} 이야기", ""]
    for p in sorted(values.get("pages", []), key=lambda x: x["page"]):
        lines.append(f"**p{p['page']}.** {p['text']}")
    lines.append("")
    if values.get("retry_count"):
        lines.append(f"🔁 검증 실패로 {values['retry_count']}회 재작성해서 완성했어요.")
    if values.get("saved_path"):
        lines.append(f"💾 파일로 저장했어요: `{values['saved_path']}`")
    lines.append("")
    lines.append("새 동화를 만들려면 **다음 단어들**을 입력해주세요! 지난 단어는 복습으로 살짝 등장해요. 😊")
    return "\n".join(lines)


# ── 채팅 입력 처리 (words → age → theme 순서로 수집) ─────────
user_msg = st.chat_input("메시지를 입력하세요...")

if user_msg:
    st.session_state["messages"].append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    stage = st.session_state["stage"]
    pending = st.session_state["pending"]

    if stage == "words":
        words = [w for w in re.split(r"[,\s]+", user_msg.strip()) if w]
        result = check_words.invoke({"words": words})
        if result["ok"]:
            pending["words"] = words
            st.session_state["stage"] = "age"
            say(f"좋아요! **{', '.join(words)}** 로 동화를 만들게요. 🌟\n\n아이가 몇 살인가요? (숫자로)")
        else:
            problems = "\n".join(f"- {p}" for p in result["problems"])
            say(f"앗, 이 단어들은 사용할 수 없어요. 🙏\n\n{problems}\n\n단어를 다시 입력해주세요!")

    elif stage == "age":
        m = re.search(r"\d+", user_msg)
        if not m:
            say("나이를 숫자로 알려주세요! 예) `4`")
        else:
            pending["age"] = int(m.group())
            style = "의성어 중심의 아주 짧은 문장(영아용)" if pending["age"] <= 3 else "이야기 중심 문장(표준)"
            st.session_state["stage"] = "theme"
            say(f"{pending['age']}살이군요! **{style}** 스타일로 쓸게요. ✍️\n\n"
                f"동화의 테마를 알려주세요. 예) `숲속 모험`, `바닷속 여행`, `우주 소풍`")

    elif stage == "theme":
        theme = user_msg.strip()
        values, trace = run_generation(pending["words"], pending["age"], theme)

        if values.get("status") == "rejected":
            say("앗, 단어 검사에서 거절됐어요: " + "; ".join(values.get("issues", [])), trace=trace)
        else:
            say(
                story_markdown(values),
                trace=trace,
                illust=values.get("illust_prompts", []),
            )
        st.session_state["stage"] = "words"
        st.session_state["pending"] = {}

    st.rerun()
