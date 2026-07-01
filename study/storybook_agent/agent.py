import asyncio
import base64
import functools
from openai import OpenAI
from google.adk.agents import Agent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = LiteLlm(model="openai/gpt-4.1")

# ── 프롬프트 ──────────────────────────────────────────────────────────────────

STORY_WRITER_DESCRIPTION = "테마를 받아 5페이지 분량의 어린이 동화를 한국어로 작성하는 에이전트"

STORY_WRITER_INSTRUCTION = """
당신은 창의적인 어린이 동화 작가입니다.
사용자가 테마를 주면 5페이지 분량의 한국어 어린이 동화를 작성하세요.

규칙:
- 각 페이지: 어린이에게 적합한 짧고 간단한 1~2문장 (한국어)
- 각 페이지: 삽화가를 위한 생생한 시각적 설명 (누가, 무엇을, 어디서, 색상, 분위기) (한국어)
- 말투: 따뜻하고 상상력 넘치며 연령에 적합하게

스토리가 완성되면 save_story()를 아래 두 인자로 호출하세요:

pages:
[
  {"page": 1, "text": "...", "visual": "..."},
  {"page": 2, "text": "...", "visual": "..."},
  {"page": 3, "text": "...", "visual": "..."},
  {"page": 4, "text": "...", "visual": "..."},
  {"page": 5, "text": "...", "visual": "..."}
]

characters: 등장하는 모든 캐릭터의 외형을 한 문장으로 묘사 (예: "토토: 작고 하얀 토끼, 파란 눈, 분홍 귀 / 다람쥐 친구들: 갈색 다람쥐, 작은 도토리 가방")

저장 후 각 페이지의 텍스트와 시각적 설명을 한국어로 요약해서 출력하세요.
"""

ILLUSTRATOR_DESCRIPTION = "스토리 State를 읽어 각 페이지의 이미지를 생성하고 Artifact로 저장하는 에이전트"

ILLUSTRATOR_INSTRUCTION = """
당신은 어린이 동화책 삽화가입니다.
스토리는 이미 작성되어 세션 State에 저장되어 있습니다.

호출되면 즉시 generate_illustrations()를 인자 없이 실행하세요.
이 도구는:
1. State에서 모든 스토리 페이지를 읽습니다
2. 각 페이지마다 이미지를 1장 생성합니다
3. 각 이미지를 Artifact로 저장합니다 (page_1.png, page_2.png, ...)

도구 실행 완료 후 결과를 한국어로 보고하세요:
- 몇 페이지가 완성되었는지
- 각 이미지의 파일명
"""

# ── 도구 ──────────────────────────────────────────────────────────────────────

def save_story(tool_context: ToolContext, pages: list, characters: str = ""):
    """스토리 페이지와 캐릭터 정보를 세션 State에 저장합니다.

    Args:
        pages: 'page'(int), 'text'(str), 'visual'(str) 키를 가진 dict의 리스트
        characters: 모든 등장인물의 외형 묘사 문자열 (이미지 일관성 유지용)
    """
    tool_context.state["story_pages"] = pages
    tool_context.state["story_characters"] = characters
    return {"status": "저장 완료", "page_count": len(pages)}


async def generate_illustrations(tool_context: ToolContext):
    """State에서 스토리 페이지를 읽어 각 페이지 이미지를 생성하고 Artifact로 저장합니다."""
    pages = tool_context.state.get("story_pages", [])
    if not pages:
        return {"status": "error", "message": "State에 스토리 페이지가 없습니다."}

    pages = pages[:5]
    characters = tool_context.state.get("story_characters", "")
    character_prefix = f"캐릭터 설정 (반드시 유지): {characters}. " if characters else ""

    client = OpenAI()
    results = []
    loop = asyncio.get_event_loop()

    for page in pages:
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

        filename = f"page_{page['page']}.png"
        await tool_context.save_artifact(
            filename=filename,
            artifact=types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        )
        results.append({"page": page["page"], "filename": filename})

    return {"status": "완료", "images": results}


# ── 에이전트 ──────────────────────────────────────────────────────────────────

story_writer_agent = Agent(
    name="StoryWriterAgent",
    description=STORY_WRITER_DESCRIPTION,
    instruction=STORY_WRITER_INSTRUCTION,
    tools=[save_story],
    model=MODEL,
)

illustrator_agent = Agent(
    name="IllustratorAgent",
    description=ILLUSTRATOR_DESCRIPTION,
    instruction=ILLUSTRATOR_INSTRUCTION,
    tools=[generate_illustrations],
    model=MODEL,
)

root_agent = SequentialAgent(
    name="StorybookAgent",
    description="스토리 작성과 삽화 생성을 순서대로 실행하는 어린이 동화책 에이전트",
    sub_agents=[story_writer_agent, illustrator_agent],
)
