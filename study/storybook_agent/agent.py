import httpx
from openai import AsyncOpenAI
from google.adk.agents import Agent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = LiteLlm(model="openai/gpt-4o")

# ── Prompts ───────────────────────────────────────────────────────────────────

STORY_WRITER_DESCRIPTION = (
    "Children's storybook writer that creates 5-page stories "
    "with page text and visual descriptions."
)

STORY_WRITER_INSTRUCTION = """
You are a creative children's storybook writer.
When the user gives you a theme, write a 5-page children's story.

Rules:
- Each page: 1-2 short, simple sentences suitable for young children
- Each page: a vivid visual description for the illustrator (who, what, where, colors, mood)
- Tone: warm, imaginative, age-appropriate

Once the story is ready, call save_story() with this exact structure:
[
  {"page": 1, "text": "...", "visual": "..."},
  {"page": 2, "text": "...", "visual": "..."},
  {"page": 3, "text": "...", "visual": "..."},
  {"page": 4, "text": "...", "visual": "..."},
  {"page": 5, "text": "...", "visual": "..."}
]

After saving, print a summary showing each page's text and visual description.
"""

ILLUSTRATOR_DESCRIPTION = (
    "Children's book illustrator that generates DALL-E 3 images "
    "for each story page and saves them as Artifacts."
)

ILLUSTRATOR_INSTRUCTION = """
You are a children's book illustrator.
A story has already been written and stored in session state.

When called, immediately invoke generate_illustrations() with no arguments.
The tool will:
1. Read all story pages from state
2. Generate one DALL-E 3 image per page
3. Save each image as an Artifact (page_1.png, page_2.png, ...)

After the tool completes, report the results:
- Which pages were illustrated
- The filename of each saved image
"""

# ── Tools ─────────────────────────────────────────────────────────────────────

async def save_story(tool_context: ToolContext, pages: list):
    """Save story pages to session state so the illustrator can read them.

    Args:
        pages: List of dicts, each with keys 'page' (int), 'text' (str), 'visual' (str).
    """
    tool_context.state["story_pages"] = pages
    return {"status": "saved", "page_count": len(pages)}


async def generate_illustrations(tool_context: ToolContext):
    """Read story pages from state and generate a DALL-E 3 image for each page.
    Each image is saved as an Artifact named page_<n>.png.
    """
    pages = tool_context.state.get("story_pages", [])
    if not pages:
        return {"status": "error", "message": "No story pages found in state."}

    client = AsyncOpenAI()
    results = []

    for page in pages:
        page_num = page["page"]
        visual = page["visual"]

        response = await client.images.generate(
            model="dall-e-3",
            prompt=(
                f"Children's book illustration, soft watercolor style, "
                f"cute and friendly characters: {visual}"
            ),
            size="1024x1024",
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url

        async with httpx.AsyncClient() as http_client:
            img_response = await http_client.get(image_url)
            image_bytes = img_response.content

        filename = f"page_{page_num}.png"
        await tool_context.save_artifact(
            filename=filename,
            artifact=types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        )
        results.append({"page": page_num, "filename": filename})

    return {"status": "completed", "images": results}


# ── Agents ────────────────────────────────────────────────────────────────────

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
    description="Orchestrates story writing then illustration for a children's book.",
    sub_agents=[story_writer_agent, illustrator_agent],
)
