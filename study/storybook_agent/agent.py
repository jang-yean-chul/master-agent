import asyncio
import base64
import functools
import io
import os
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from google.adk.agents import Agent, SequentialAgent, ParallelAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = LiteLlm(model="openai/gpt-4.1")

PAGE_COUNT = 5

# 이미지에 한글 텍스트를 그릴 때 사용하는 폰트 (Windows 맑은 고딕)
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"

# 완성된 삽화(텍스트 포함)를 파일로도 저장하는 로컬 폴더
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# ── 프롬프트 ──────────────────────────────────────────────────────────────────

STORY_WRITER_DESCRIPTION = "테마를 받아 5페이지 분량의 어린이 동화를 한국어로 작성하는 에이전트"

STORY_WRITER_INSTRUCTION = """
당신은 창의적인 어린이 동화 작가입니다.
사용자가 테마를 주면 5페이지 분량의 한국어 어린이 동화를 작성하세요.

규칙:
- 각 페이지: 어린이에게 적합한 짧고 간단한 1~2문장 (한국어)
- 각 페이지: 삽화가를 위한 생생한 시각적 설명 (누가, 무엇을, 어디서, 색상, 분위기) (한국어)
- 말투: 따뜻하고 상상력 넘치며 연령에 적합하게

스토리가 완성되면 save_story()를 아래 세 인자로 호출하세요:

title: 동화책 제목 (한국어)

pages:
[
  {"page": 1, "text": "...", "visual": "..."},
  {"page": 2, "text": "...", "visual": "..."},
  {"page": 3, "text": "...", "visual": "..."},
  {"page": 4, "text": "...", "visual": "..."},
  {"page": 5, "text": "...", "visual": "..."}
]

characters: 등장하는 모든 캐릭터의 외형을 한 문장으로 묘사 (예: "토토: 작고 하얀 토끼, 파란 눈, 분홍 귀 / 다람쥐 친구들: 갈색 다람쥐, 작은 도토리 가방")

저장 후 제목과 각 페이지의 텍스트, 시각적 설명을 한국어로 요약해서 출력하세요.
"""

ILLUSTRATOR_INSTRUCTION = """
당신은 어린이 동화책 삽화가입니다.
스토리는 이미 작성되어 세션 State에 저장되어 있으며, 당신은 담당 페이지 한 장의 삽화를 그립니다.

호출되면 즉시 generate_illustration()을 인자 없이 실행하세요.
도구 실행이 끝나면 저장된 이미지 파일명을 한국어로 간단히 보고하세요.
"""

# ── 콜백 (진행 상황 표시) ──────────────────────────────────────────────────────

def writer_progress_callback(callback_context: CallbackContext):
    """스토리 작성 시작을 알리는 콜백."""
    print("📖 스토리 작성 중...")
    return None


def make_illustrator_progress_callback(page_num: int):
    """페이지별 삽화 생성 시작을 알리는 콜백을 만듭니다."""
    def callback(callback_context: CallbackContext):
        print(f"🎨 이미지 {page_num}/{PAGE_COUNT} 생성 중...")
        return None
    return callback


def compile_storybook_callback(callback_context: CallbackContext):
    """모든 작업 완료 후 State의 삽화들을 순서대로 묶어 동화책 PDF 한 파일로 만들고
    완성된 동화책을 최종 출력합니다."""
    state = callback_context.state
    title = state.get("story_title", "제목 없음")
    pages = state.get("story_pages", [])

    # 1~5페이지 순서대로 삽화(base64) 수집 → PDF로 합침
    page_images = []
    for page in pages[:PAGE_COUNT]:
        encoded = state.get(f"page_image_{page['page']}")
        if encoded:
            page_images.append(base64.b64decode(encoded))
    pdf_path = build_storybook_pdf(page_images)

    lines = [f"📚 완성된 동화책: 《{title}》", ""]
    for page in pages[:PAGE_COUNT]:
        lines.append(f"[{page['page']}페이지] {page['text']}")
        lines.append("")
    if pdf_path:
        lines.append(f"📄 동화책 파일(5페이지): {pdf_path}")
    else:
        lines.append("⚠️ PDF 생성에 실패했습니다.")
    text = "\n".join(lines).rstrip()

    print(text)
    return types.Content(role="model", parts=[types.Part(text=text)])

# ── 이미지 텍스트 합성 ─────────────────────────────────────────────────────────

def _wrap_korean(draw, text, font, max_width):
    """한글 텍스트를 이미지 폭에 맞춰 줄바꿈합니다."""
    lines = []
    line = ""
    for ch in text:
        if ch == "\n":
            lines.append(line)
            line = ""
            continue
        if draw.textlength(line + ch, font=font) <= max_width:
            line += ch
        else:
            lines.append(line)
            line = ch
    if line:
        lines.append(line)
    return lines


def overlay_text(image_bytes: bytes, text: str) -> bytes:
    """삽화 하단에 반투명 밴드를 깔고 그 위에 동화 텍스트를 그려 넣습니다."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img, "RGBA")

    try:
        font = ImageFont.truetype(FONT_PATH, 40)
    except OSError:
        font = ImageFont.load_default()

    margin = 40
    line_height = 52
    lines = _wrap_korean(draw, text, font, width - 2 * margin)
    band_height = line_height * len(lines) + 2 * margin
    band_top = height - band_height

    # 가독성을 위한 반투명 흰색 밴드
    draw.rectangle([0, band_top, width, height], fill=(255, 255, 255, 210))

    y = band_top + margin
    for line in lines:
        draw.text((margin, y), line, font=font, fill=(30, 30, 30, 255))
        y += line_height

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def build_storybook_pdf(page_images: list):
    """1~5페이지 삽화를 순서대로 묶어 동화책 PDF 한 파일로 저장합니다.

    Args:
        page_images: 페이지 순서대로 정렬된 이미지 바이트 리스트

    Returns:
        저장된 PDF 파일 경로 문자열 (실패 시 None)
    """
    if not page_images:
        return None
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pdf_path = os.path.join(OUTPUT_DIR, "storybook.pdf")
        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in page_images]
        images[0].save(
            pdf_path,
            format="PDF",
            save_all=True,
            append_images=images[1:],
        )
        return pdf_path
    except OSError:
        return None  # 배포 환경 등 쓰기 불가 시 무시


# ── 도구 ──────────────────────────────────────────────────────────────────────

def save_story(tool_context: ToolContext, title: str, pages: list, characters: str = ""):
    """스토리 제목, 페이지, 캐릭터 정보를 세션 State에 저장합니다.

    Args:
        title: 동화책 제목
        pages: 'page'(int), 'text'(str), 'visual'(str) 키를 가진 dict의 리스트
        characters: 모든 등장인물의 외형 묘사 문자열 (이미지 일관성 유지용)
    """
    tool_context.state["story_title"] = title
    tool_context.state["story_pages"] = pages
    tool_context.state["story_characters"] = characters
    return {"status": "저장 완료", "title": title, "page_count": len(pages)}


def make_generate_illustration(page_index: int):
    """지정된 페이지 한 장의 삽화를 생성하는 도구를 만듭니다."""
    async def generate_illustration(tool_context: ToolContext):
        """담당 페이지의 이미지를 생성하고 Artifact로 저장합니다."""
        pages = tool_context.state.get("story_pages", [])
        if page_index >= len(pages):
            return {"status": "error", "message": f"{page_index + 1}페이지가 State에 없습니다."}

        page = pages[page_index]
        characters = tool_context.state.get("story_characters", "")
        character_prefix = f"캐릭터 설정 (반드시 유지): {characters}. " if characters else ""

        client = OpenAI()
        loop = asyncio.get_event_loop()
        generate_fn = functools.partial(
            client.images.generate,
            model="gpt-image-1",
            prompt=(
                f"어린이 동화책 삽화, 부드러운 수채화 스타일, 귀엽고 친근한 캐릭터. "
                f"{character_prefix}"
                f"이번 장면: {page['visual']}"
            ),
            size="1024x1024",
            n=1,
        )
        response = await loop.run_in_executor(None, generate_fn)
        image_bytes = base64.b64decode(response.data[0].b64_json)

        # 생성된 삽화 하단에 동화 텍스트를 합성
        image_bytes = overlay_text(image_bytes, page["text"])

        filename = f"page_{page['page']}.png"

        # 1) ADK Artifact로 저장 (Web UI에서 확인)
        await tool_context.save_artifact(
            filename=filename,
            artifact=types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        )

        # 2) 완성된 삽화를 State에 저장 → 마지막 콜백이 순서대로 PDF로 합침
        #    (페이지별 고유 키를 사용해 병렬 실행 중 State 충돌 방지)
        tool_context.state[f"page_image_{page['page']}"] = base64.b64encode(
            image_bytes
        ).decode()

        return {"status": "완료", "page": page["page"], "filename": filename}

    return generate_illustration


# ── 에이전트 ──────────────────────────────────────────────────────────────────

story_writer_agent = Agent(
    name="StoryWriterAgent",
    description=STORY_WRITER_DESCRIPTION,
    instruction=STORY_WRITER_INSTRUCTION,
    tools=[save_story],
    model=MODEL,
    before_agent_callback=writer_progress_callback,
)

# 페이지별 삽화 에이전트 5개 (ParallelAgent가 동시에 실행)
illustrator_agents = [
    Agent(
        name=f"IllustratorAgent{i + 1}",
        description=f"{i + 1}페이지의 삽화를 생성하는 에이전트",
        instruction=ILLUSTRATOR_INSTRUCTION,
        tools=[make_generate_illustration(i)],
        model=MODEL,
        before_agent_callback=make_illustrator_progress_callback(i + 1),
    )
    for i in range(PAGE_COUNT)
]

parallel_illustrator_agent = ParallelAgent(
    name="ParallelIllustratorAgent",
    description="5개 페이지의 삽화를 동시에 생성하는 병렬 에이전트",
    sub_agents=illustrator_agents,
)

root_agent = SequentialAgent(
    name="StorybookAgent",
    description="스토리 작성 후 삽화를 병렬 생성하는 어린이 동화책 에이전트",
    sub_agents=[story_writer_agent, parallel_illustrator_agent],
    after_agent_callback=compile_storybook_callback,
)
