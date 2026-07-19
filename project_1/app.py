"""
WordiTale (워디테일) — Streamlit 대화형 UI

채팅으로 학습 단어 → 아이 나이 → 테마를 차례로 받아 동화를 생성한다.
생성 중에는 진행 상황을 워디(동화 요정)의 말로 실시간 중계하고,
사이드바에서 아이별 메모리(배운 단어)를 보여준다.
기술 요소(그래프 구조·노드 로그·LLM 모드)는 개발자 모드에서만 노출한다.

실행: streamlit run app.py
배포: Streamlit Cloud — Secrets에 OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 등록
      (키가 없으면 mock 모드로 동작해 키 없이도 데모 가능)
"""
from __future__ import annotations

import os
import re
import sys
from html import escape

import dotenv

# .env를 앱 파일 기준 절대 경로로 로드 — 실행 위치(cwd)와 무관하게 키를 찾는다
dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ── Streamlit Cloud secrets → 환경변수 (배포 시 API 키 주입) ──
# 로컬은 .env(dotenv)로, 클라우드는 st.secrets로 키가 들어온다.
for _key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
    if not os.environ.get(_key):
        try:
            os.environ[_key] = st.secrets[_key]
        except Exception:  # secrets.toml 없음 · 키 미등록 → mock 모드
            pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from worditale import (  # noqa: E402
    HERO_DEFAULT,
    MAX_WORDS,
    MIN_WORDS,
    check_words,
    graph,
    image_provider,
    llm_provider,
)
from worditale import voice_store  # noqa: E402

st.set_page_config(page_title="WordiTale", page_icon="🐰", layout="centered")

# ── 전역 스타일: 둥근 산세리프 + 동화 본문 조판 (DESIGN.md) ──
st.markdown(
    """
<style>
@import url('https://cdn.jsdelivr.net/gh/moonspam/NanumSquareRound@master/nanumsquareround.min.css');
html, body, [class*="st-"], .stMarkdown, button, input, textarea {
    font-family: 'NanumSquareRound', 'Malgun Gothic', sans-serif !important;
}
/* Streamlit 아이콘(확장 패널 화살표 등)은 Material Symbols 폰트를 유지해야 함
   — 전역 글꼴에 덮이면 keyboard_arrow_right 같은 원문 텍스트로 보인다 */
[data-testid="stIconMaterial"], [class*="material-symbols"] {
    font-family: 'Material Symbols Rounded' !important;
}
/* 헤더 배너 — 살구 커밋 표면 */
.wordi-hero {
    background: #DE5F33; color: #FFFFFF;
    padding: 1.1rem 1.4rem; border-radius: 1rem; margin-bottom: 0.6rem;
}
.wordi-hero h1 { margin: 0; font-size: 1.9rem; color: #FFFFFF; }
.wordi-hero p  { margin: 0.35rem 0 0; color: #FFFFFF; font-size: 0.95rem; }
/* 동화 본문 — 화면의 주인공: UI보다 크고 또렷하게 */
.wordi-story { font-size: 1.28rem; line-height: 1.95; color: #33261D; }
.wordi-story h3 { margin-bottom: 0.6rem; }
.wordi-story .page-no {
    display: inline-block; background: #F9E0CF; color: #8A3D1E;
    border-radius: 0.6rem; padding: 0 0.55rem; margin-right: 0.45rem;
    font-size: 0.85rem; font-weight: 700; vertical-align: 0.15rem;
}
/* 보조 텍스트도 AA 대비 확보 */
[data-testid="stCaptionContainer"], .stCaption { color: #6B5546 !important; }
@media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
}
</style>
""",
    unsafe_allow_html=True,
)

# ── 노드 실행 중계: 워디의 말 (개발자 모드에선 노드명 병기) ──
NODE_LABELS = {
    "check_words": "🔍 단어들을 살펴보고 있어요 — 우리 아이에게 딱 맞는지 확인!",
    "reject_input": "🙏 이번 단어들로는 동화를 만들기 어려워요",
    "plan_story": "📝 줄거리를 짜고 있어요 — 페이지마다 어떤 장면이 좋을까?",
    "write_story_toddler": "✍️ 이야기를 처음부터 끝까지 한 호흡으로 쓰고 있어요 (영아용 의성어 스타일)",
    "write_story_standard": "✍️ 이야기를 처음부터 끝까지 한 호흡으로 쓰고 있어요 (스토리 스타일)",
    "polish_story": "🪡 문장이 매끄럽게 이어지도록 한 번 더 통독하며 다듬고 있어요",
    "plan_illustrations": "🎬 삽화 연출을 짜고 있어요 — 배경·시간·소품이 쪽마다 이어지도록",
    "finalize": "✨ 이야기를 곱게 마무리하고 있어요",
    "save_storybook": "📖 동화책으로 예쁘게 엮고 있어요",
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
- 무섭거나 위험한 단어(칼, 총 등)는 자동으로 거절돼요 — 아이를 위한 이중 안전 필터가 지켜보고 있어요

**2. 나이 입력** 👶
- **3세 이하**: 의성어 중심의 아주 짧은 문장으로 써요 → "나비를 봐요. 팔랑팔랑!"
- **4세 이상**: 이야기가 있는 문장으로 써요 → "토토는 나비를 따라 꽃밭으로 갔어요."
- `20개월`처럼 개월 수로 입력해도 알아들어요

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

**입력 도중 마음이 바뀌면** ↩️ — `다시`라고 입력하면 언제든 단어 고르기부터 새로 시작할 수 있어요
"""

# 채팅 입력창 안내 — 지금 무엇을 입력할 차례인지 항상 보여준다
PLACEHOLDERS = {
    "words": f"배울 단어 {MIN_WORDS}~{MAX_WORDS}개를 쉼표로 입력해주세요 (예: 사과, 구름, 나비, 바람, 무지개)",
    "age": "아이 나이를 숫자로 알려주세요 (예: 4 또는 20개월)",
    "theme": "동화 테마를 알려주세요 (예: 숲속 모험)",
    "confirm": "테마를 바꾸고 싶으면 새 테마를 입력해주세요",
}

BACK_WORDS = {"다시", "뒤로", "취소", "처음부터"}


# ── 세션 상태 초기화 ─────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": GREETING}]
if "stage" not in st.session_state:
    st.session_state["stage"] = "words"   # words → age → theme → confirm → (생성) → words
if "pending" not in st.session_state:
    st.session_state["pending"] = {}      # 수집 중인 입력 {words, age, theme}


def say(content: str, **extra) -> None:
    st.session_state["messages"].append({"role": "assistant", "content": content, **extra})


def restart(message: str = "좋아요, 처음부터 다시 시작해요! ↩️\n\n배울 단어를 쉼표로 구분해 입력해주세요.") -> None:
    st.session_state["stage"] = "words"
    st.session_state["pending"] = {}
    say(message)


# ── 사이드바: 아이별 메모리 + 개발자 모드 ────────────────────
with st.sidebar:
    st.header("👶 아이 설정")
    child_name = st.text_input("아이 이름 (이름별로 배운 단어가 기억돼요)", value="우리아이").strip() or "우리아이"
    hero = st.text_input(
        "주인공 캐릭터 (성격 + 동물/사람 + 이름)",
        value=HERO_DEFAULT,
        help="모든 페이지와 삽화에서 같은 모습으로 유지돼요. 예) 호기심 많은 아기 곰 보리",
    )
    config = {"configurable": {"thread_id": f"child-{child_name}"}}

    snapshot = graph.get_state(config)
    learned = snapshot.values.get("learned_words", []) if snapshot.values else []
    if learned:
        st.markdown(f"🌱 지금까지 **{len(learned)}개**의 단어와 친구가 됐어요")
        st.caption(", ".join(learned))
    else:
        st.markdown("🌱 아직 만난 단어가 없어요 — 첫 동화를 만들어보세요!")

    st.divider()

    # 대화 초기화 — 실수 클릭 방지 2단계 확인
    if st.session_state.get("confirm_reset"):
        st.warning("지금까지의 대화가 모두 사라져요. 계속할까요?")
        c1, c2 = st.columns(2)
        if c1.button("네, 초기화", use_container_width=True):
            st.session_state["messages"] = [{"role": "assistant", "content": GREETING}]
            st.session_state["stage"] = "words"
            st.session_state["pending"] = {}
            st.session_state["confirm_reset"] = False
            st.rerun()
        if c2.button("취소", use_container_width=True):
            st.session_state["confirm_reset"] = False
            st.rerun()
    elif st.button("💬 대화 초기화"):
        st.session_state["confirm_reset"] = True
        st.rerun()

    st.divider()

    # 삽화 설정 — 이미지 공급자(OpenAI)가 있을 때만 그림 생성 가능
    st.markdown("**🎨 삽화 그림**")
    ILLUST_OPTIONS = {
        "빠른 스케치 (테스트용·저렴)": "low",
        "예쁜 그림 (최종본용)": "medium",
        "그리지 않기 (프롬프트만)": "off",
    }
    if image_provider():
        illust_label = st.selectbox(
            "삽화 품질",
            list(ILLUST_OPTIONS),
            index=0,
            label_visibility="collapsed",
            help="그림 한 장마다 API 비용이 들어요. 연습은 빠른 스케치로, 아이에게 줄 최종본은 예쁜 그림으로!",
        )
        illust_quality = ILLUST_OPTIONS[illust_label]
        illust_caption = st.checkbox(
            "🖋️ 그림 안에 동화 글귀 넣기",
            value=True,
            help="삽화 아래 크림색 띠에 페이지 글귀가 함께 들어가요 — 한 장씩 넘겨 읽기 좋아요.",
        )
    else:
        illust_quality = "off"
        illust_caption = True
        st.caption("그림 생성에는 OpenAI API 키가 필요해요 — 지금은 삽화 프롬프트만 만들어요.")

    st.divider()
    dev_mode = st.toggle(
        "🛠️ 개발자 모드",
        value=False,
        help="에이전트 그래프 구조, 노드 실행 로그, LLM 모드 등 내부 동작을 보여줘요.",
    )
    if dev_mode:
        mode = llm_provider() or "mock"
        st.caption(f"LLM 모드: **{mode}**" + (" (키 없이 규칙 기반 데모)" if mode == "mock" else ""))


# ── 헤더 ─────────────────────────────────────────────────────
st.markdown(
    '<div class="wordi-hero"><h1>🐰 WordiTale</h1>'
    "<p>아이가 배울 단어로 만드는, 우리 아이만의 맞춤 동화</p></div>",
    unsafe_allow_html=True,
)

# mock 모드는 숨기지 않고 명확히 알린다 — 더미 동화를 진짜로 오해하지 않도록
if not llm_provider():
    st.warning(
        "지금은 **데모 모드**예요 — API 키가 없어 규칙 기반 더미 동화가 나옵니다 "
        "(이야기 흐름·삽화 없음). 진짜 동화를 만들려면 `.env`의 API 키를 확인하고 "
        "`project_1` 폴더에서 앱을 다시 실행해주세요.",
        icon="⚠️",
    )

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
    if uploads:
        st.info("⬇️ 아래 저장 버튼을 눌러야 목소리가 보관돼요!")
        if st.button("💾 업로드한 목소리 저장", type="primary"):
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


if dev_mode:
    with st.expander("🗺️ 에이전트 그래프 구조 보기 (개발자)"):
        st.iframe(graph_html(), height=560)


# ── 그림책 렌더링 헬퍼 ───────────────────────────────────────
def build_story(values: dict) -> dict:
    """그래프 결과에서 그림책 데이터(쪽별 텍스트 + 삽화 경로)를 구성한다."""
    img_by_page = {
        ip["page"]: ip.get("image_path")
        for ip in values.get("illust_prompts", [])
    }
    return {
        "theme": values.get("theme", "동화"),
        # 글귀가 이미지에 합성됐으면 렌더링 때 텍스트 블록을 중복 표시하지 않는다
        "captioned": bool(values.get("illust_caption", True)),
        "pages": [
            {**p, "image_path": img_by_page.get(p["page"])}
            for p in sorted(values.get("pages", []), key=lambda x: x["page"])
        ],
    }


def render_story(story: dict) -> None:
    """그림책 렌더링 — 삽화(st.image) + 본문 전용 블록(크고 또렷하게)."""
    st.markdown(
        f'<div class="wordi-story"><h3>📖 {escape(story["theme"])} 이야기</h3></div>',
        unsafe_allow_html=True,
    )
    for p in story["pages"]:
        img = p.get("image_path")
        has_img = img and Path(img).exists()
        if has_img:
            st.image(img, use_container_width=True)
        if not (has_img and story.get("captioned")):
            # 글귀가 이미지 안에 합성된 경우엔 텍스트 블록 중복 표시 생략
            st.markdown(
                f'<div class="wordi-story"><p><span class="page-no">{p["page"]}쪽</span>'
                f'{escape(p["text"])}</p></div>',
                unsafe_allow_html=True,
            )


def story_footer(values: dict) -> str:
    lines = []
    if values.get("retry_count"):
        lines.append(f"🔁 워디가 {values['retry_count']}번 더 정성껏 다듬어서 완성했어요!")
    lines.append("")
    lines.append("새 동화를 만들려면 **다음 단어들**을 입력해주세요! 지난 단어는 복습으로 살짝 등장해요. 😊")
    return "\n".join(lines)


# ── 지난 대화 그리기 ─────────────────────────────────────────
for i, msg in enumerate(st.session_state["messages"]):
    with st.chat_message(msg["role"]):
        if msg.get("story"):
            render_story(msg["story"])  # 그림책(삽화 + 본문 블록)이 먼저
        # 동화 본문 HTML은 어시스턴트 메시지에만 허용 (사용자 입력은 그대로 텍스트)
        st.markdown(msg["content"], unsafe_allow_html=(msg["role"] == "assistant"))
        if msg.get("download"):
            st.download_button(
                "📥 동화책 파일로 간직하기",
                data=msg["download"]["data"],
                file_name=msg["download"]["name"],
                key=f"dl-{i}",
            )
        if msg.get("trace"):
            with st.expander("🛠️ 워디가 일한 과정 보기"):
                for line in msg["trace"]:
                    st.markdown(f"- {line}")
        if msg.get("illust"):
            with st.expander("🎨 페이지별 삽화 프롬프트"):
                for ip in sorted(msg["illust"], key=lambda x: x["page"]):
                    st.markdown(f"**p{ip['page']}** — {ip['prompt']}")


# ── 동화 생성 (진행 상황을 워디의 말로 실시간 중계) ──────────
def _validate_line(update: dict | None, state: dict, dev: bool) -> str:
    """검증 노드 결과를 중계 문장으로 — 재작성이면 횟수를 누적한다."""
    issues = (update or {}).get("issues") or []
    if not issues:
        return "🔎 이야기가 잘 이어지고 단어도 모두 들어갔는지 살펴봤어요 — 통과!"
    state["retry"] += 1
    if (update or {}).get("needs_replan"):
        line = "🔎 이야기의 앞뒤 연결이 아쉬워서 줄거리 설계부터 다시 짜는 중이에요"
    else:
        line = "🔎 조금 아쉬운 부분이 있어서 한 번 더 정성껏 다듬는 중이에요"
    if dev:
        line += f" — {'; '.join(issues)} (재작성 {state['retry']}회차)"
    return line


def _illust_summary(state: dict) -> str:
    """삽화 병렬 생성 결과를 한 줄로 — 일부 실패는 숨기지 않고 알린다."""
    if not state.get("with_images"):
        return f"🎨 {state['illust']}쪽의 그림을 상상해뒀어요"
    if state["img_ok"] >= state["illust"]:
        return f"🖼️ {state['illust']}쪽의 삽화를 그렸어요 — 그림책 완성!"
    return (
        f"🖼️ {state['illust']}쪽 중 {state['img_ok']}쪽의 삽화를 그렸어요 — "
        f"몇 쪽은 그림이 잘 나오지 않아 글로만 실었어요. "
        f"같은 조건으로 다시 만들면 채워질 수 있어요!"
    )


def relay_lines(node: str, update: dict | None, state: dict, dev: bool) -> list[tuple[str, str]]:
    """스트림 이벤트 하나를 워디의 중계 (문장, 노드명) 목록으로 바꾼다.

    병렬 노드(페이지 워커·삽화)는 state에 개수만 누적했다가 모아서 한 줄로 표시한다.
    """
    lines: list[tuple[str, str]] = []
    if node == "gen_character_ref":
        if state.get("with_images"):
            lines.append(("🧸 주인공과 배경의 기준 그림을 먼저 그렸어요 — 모든 쪽이 같은 세계로 보이게", node))
        return lines
    if node == "gen_illust_prompt":
        state["illust"] += 1
        entry = ((update or {}).get("illust_prompts") or [{}])[0]
        if entry.get("image_path"):
            state["img_ok"] += 1
        return lines
    if node == "validate_story":
        line = _validate_line(update, state, dev)
    elif node == "save_storybook":
        if state["illust"]:
            lines.append((_illust_summary(state), "gen_illust_prompt"))
        line = NODE_LABELS[node]
    else:
        line = NODE_LABELS.get(node, f"⚙️ {node}")
    lines.append((line, node))
    return lines


def run_generation(words: list[str], age: int, theme: str) -> tuple[dict, list[str]]:
    trace: list[str] = []
    with_images = illust_quality != "off" and image_provider()
    state = {"illust": 0, "img_ok": 0, "retry": 0, "with_images": with_images}

    label = "🪄 동화를 만드는 중..."
    if with_images:
        label += " 그림까지 그리면 2~3분 정도 걸려요 🎨"
    elif llm_provider():
        label += " 보통 1~2분 정도 걸려요 ☕"
    with st.status(label, expanded=True) as status:
        inputs = {"target_words": words, "child_age": age, "theme": theme,
                  "hero": hero, "illust_quality": illust_quality,
                  "illust_caption": illust_caption, "demo_fail_first": False}
        for chunk in graph.stream(inputs, config, stream_mode="updates"):
            for node, update in chunk.items():
                for line, src_node in relay_lines(node, update, state, dev_mode):
                    if dev_mode:
                        line = f"{line}  `{src_node}`"
                    st.write(line)
                    trace.append(line)
        status.update(label="✨ 동화가 완성됐어요!", state="complete", expanded=False)

    return graph.get_state(config).values, trace


def story_download(values: dict) -> dict | None:
    """저장된 동화책 파일을 다운로드 데이터로 준비 (파일이 없으면 본문으로 대체)."""
    theme = values.get("theme", "동화")
    saved = values.get("saved_path")
    try:
        if saved and Path(saved).exists():
            data = Path(saved).read_text(encoding="utf-8")
        else:
            data = "\n\n".join(
                f"p{p['page']}. {p['text']}"
                for p in sorted(values.get("pages", []), key=lambda x: x["page"])
            )
        return {"name": f"{theme} 이야기.md", "data": data}
    except Exception:
        return None


def start_generation() -> None:
    """확인된 입력으로 동화를 생성하고 결과를 채팅에 추가한다."""
    p = st.session_state["pending"]
    try:
        values, trace = run_generation(p["words"], p["age"], p["theme"])
    except Exception as e:  # LLM/네트워크 등 — 입력은 보존하고 재시도 안내
        detail = f"\n\n`{type(e).__name__}: {e}`" if dev_mode else ""
        say(
            "앗, 동화를 만드는 도중에 문제가 생겼어요. 😢\n\n"
            "네트워크나 API 키 문제일 수 있어요. 입력하신 내용은 그대로 있으니, "
            "잠시 후 아래 **✨ 이대로 동화 만들기** 버튼으로 다시 시도해주세요!" + detail
        )
        st.rerun()
        return

    if values.get("status") == "rejected":
        problems = "\n".join(f"- {p_}" for p_ in values.get("issues", []))
        say(
            f"앗, 단어 검사에서 어려움이 있었어요. 🙏\n\n{problems}\n\n"
            f"괜찮아요! **다른 단어들로 다시** 시작해볼까요?\n\n예) `사과, 구름, 나비, 바람, 무지개`",
            trace=trace,
        )
    else:
        say(
            story_footer(values),
            story=build_story(values),
            trace=trace,
            illust=values.get("illust_prompts", []),
            download=story_download(values),
        )
    st.session_state["stage"] = "words"
    st.session_state["pending"] = {}
    st.rerun()


# ── 생성 확인 버튼 (theme까지 모이면 마지막으로 한 번 확인) ──
if st.session_state["stage"] == "confirm" and st.session_state["pending"].get("theme"):
    c1, c2 = st.columns(2)
    if c1.button("✨ 이대로 동화 만들기", type="primary", use_container_width=True):
        start_generation()
    if c2.button("↩️ 단어부터 다시 고르기", use_container_width=True):
        restart()
        st.rerun()


# ── 채팅 입력 처리 (words → age → theme → confirm 순서) ──────
# key 고정: placeholder가 단계마다 바뀌어도 위젯이 재생성되지 않게 (커서 유지)
user_msg = st.chat_input(PLACEHOLDERS[st.session_state["stage"]], key="chat-input")

# 매 렌더링 후 입력창에 자동 포커스 — 단계가 넘어가도 커서가 이어진다
components.html(
    """<script>
    const doc = window.parent.document;
    const input = doc.querySelector('[data-testid="stChatInput"] textarea')
               || doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
    if (input) { input.focus(); }
    </script>""",
    height=0,
)

if user_msg:
    st.session_state["messages"].append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    stage = st.session_state["stage"]
    pending = st.session_state["pending"]
    text = user_msg.strip()

    # 어느 단계에서든 "다시/뒤로"로 처음부터
    if stage != "words" and text in BACK_WORDS:
        restart()
        st.rerun()

    if stage == "words":
        # 쉼표가 있으면 쉼표로만 나눠 "빨간 사과" 같은 두 단어 표현도 하나로 유지
        if "," in text:
            words = [w.strip() for w in text.split(",") if w.strip()]
        else:
            words = [w for w in re.split(r"\s+", text) if w]
        result = check_words.invoke({"words": words})
        if result["ok"]:
            pending["words"] = words
            st.session_state["stage"] = "age"
            say(f"좋아요! **{', '.join(words)}** 로 동화를 만들게요. 🌟\n\n아이가 몇 살인가요? (예: `4` 또는 `20개월`)")
        else:
            problems = "\n".join(f"- {p}" for p in result["problems"])
            say(f"앗, 이 단어들은 사용할 수 없어요. 🙏\n\n{problems}\n\n단어를 다시 입력해주세요!")

    elif stage == "age":
        m = re.search(r"\d+", text)
        if m and "개월" in text:
            age = max(1, round(int(m.group()) / 12))
        elif m:
            age = int(m.group())
        else:
            age = None
        if age is None:
            say("나이를 숫자로 알려주세요! 예) `4` 또는 `20개월`")
        elif not 1 <= age <= 10:
            say(f"음, **{age}살**은 조금 어려워요. 😅 WordiTale은 **1~10살** 아이에게 맞춰 동화를 만들어요.\n\n나이를 다시 알려주세요!")
        else:
            pending["age"] = age
            style = "의성어 중심의 아주 짧은 문장(영아용)" if age <= 3 else "이야기 중심 문장(표준)"
            st.session_state["stage"] = "theme"
            say(f"{age}살이군요! **{style}** 스타일로 쓸게요. ✍️\n\n"
                f"동화의 테마를 알려주세요. 예) `숲속 모험`, `바닷속 여행`, `우주 소풍`")

    elif stage in ("theme", "confirm"):
        # confirm 단계에서 텍스트를 입력하면 테마를 바꾼 것으로 처리
        pending["theme"] = text
        st.session_state["stage"] = "confirm"
        say(
            f"준비 완료! ✨ 이렇게 만들게요.\n\n"
            f"- 📚 단어: **{', '.join(pending['words'])}**\n"
            f"- 👶 나이: **{pending['age']}살**\n"
            f"- 🗺️ 테마: **{pending['theme']}**\n\n"
            f"아래 **✨ 이대로 동화 만들기** 버튼을 눌러주세요!\n"
            f"테마를 바꾸려면 새 테마를 입력하고, 처음부터 하려면 `다시`라고 해주세요."
        )

    st.rerun()
