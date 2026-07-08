import dotenv

dotenv.load_dotenv()

import asyncio
import base64
import streamlit as st
from agents import Agent, Runner, SQLiteSession, WebSearchTool, FileSearchTool, ImageGenerationTool

st.set_page_config(page_title="Life Coach Agent", page_icon="🌱")
st.title("🌱 Life Coach Agent")

# Replace with your actual vector store ID
VECTOR_STORE_ID = "vs_xxxxxxxxxxxxxxxx"

# Agent Setup
if "agent" not in st.session_state:
    st.session_state["agent"] = Agent(
        name="Life Coach",
        instructions="""You are a warm, supportive life coach with creative abilities. Your role is to:
        - Help users set and achieve personal goals
        - Provide motivational advice and encouragement
        - Suggest practical strategies for self-improvement
        - Track and reference the user's personal goals and journal
        - Create visual motivation through images

        You have access to the following tools:
            - Web Search Tool: Find motivational content, tips, and research.
            - File Search Tool: Search the user's personal goals and journal entries. Always check goals before giving personalized advice.
            - Image Generation Tool: Create vision boards, motivational posters, and celebratory images. Use this when:
                - The user asks for a vision board
                - The user achieves a goal (create a celebration image)
                - The user needs visual motivation
                - The user asks for a motivational poster

        Always be empathetic, positive, and actionable.
        Reference the user's specific goals when giving advice.
        When creating images, make them colorful, inspiring, and relevant to the user's goals.
        """,
        tools=[
            WebSearchTool(),
            FileSearchTool(
                vector_store_ids=[VECTOR_STORE_ID],
                max_num_results=5,
            ),
            ImageGenerationTool(),
        ],
    )
agent = st.session_state["agent"]

# Session Memory
if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "life-coach-session",
        "life-coach-memory.db",
    )
session = st.session_state["session"]


# Paint Chat History
async def paint_history():
    messages = await session.get_items()
    for message in messages:
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message["content"])
                else:
                    if message["type"] == "message":
                        for content in message.get("content", []):
                            if isinstance(content, dict):
                                if content.get("type") == "output_text":
                                    st.write(content["text"])
                                elif content.get("type") == "output_image":
                                    image_bytes = base64.b64decode(
                                        content["image_base64"]
                                    )
                                    st.image(image_bytes)
                            elif isinstance(content, str):
                                st.write(content)
        if "type" in message and message["type"] == "web_search_call":
            with st.chat_message("ai"):
                st.write("🔍 Searched the web...")
        if "type" in message and message["type"] == "file_search_call":
            with st.chat_message("ai"):
                st.write("📂 Searched your goals...")
        if "type" in message and message["type"] == "image_generation_call":
            with st.chat_message("ai"):
                st.write("🎨 Generating image...")


asyncio.run(paint_history())


# Status Updates
def update_status(status_container, event_type):
    status_map = {
        "response.web_search_call.in_progress": (
            "🔍 Searching the web...",
            "running",
        ),
        "response.web_search_call.completed": (
            "✅ Web search completed.",
            "complete",
        ),
        "response.file_search_call.in_progress": (
            "📂 Searching your goals...",
            "running",
        ),
        "response.file_search_call.completed": (
            "✅ Found relevant goals.",
            "complete",
        ),
        "response.image_generation_call.in_progress": (
            "🎨 Creating your image...",
            "running",
        ),
        "response.image_generation_call.generating": (
            "🎨 Generating image...",
            "running",
        ),
        "response.image_generation_call.completed": (
            "✅ Image created!",
            "complete",
        ),
        "response.completed": (" ", "complete"),
    }
    if event_type in status_map:
        label, state = status_map[event_type]
        status_container.update(label=label, state=state)


# Run Agent with Streaming
async def run_agent(message):
    with st.chat_message("ai"):
        status_container = st.status("🤔 Thinking...", expanded=False)
        text_placeholder = st.empty()
        image_placeholder = st.empty()
        response = ""

        stream = Runner.run_streamed(
            agent,
            message,
            session=session,
        )

        async for event in stream.stream_events():
            if event.type == "raw_response_event":
                update_status(status_container, event.data.type)

                if event.data.type == "response.output_text.delta":
                    response += event.data.delta
                    text_placeholder.write(response)

                elif event.data.type == "response.image_gen_call.completed":
                    if hasattr(event.data, "result") and event.data.result:
                        image_bytes = base64.b64decode(event.data.result)
                        image_placeholder.image(image_bytes)


# Chat Input
prompt = st.chat_input("What's on your mind today?")

if prompt:
    with st.chat_message("human"):
        st.write(prompt)
    asyncio.run(run_agent(prompt))

# Sidebar
with st.sidebar:
    st.markdown("### 🌱 Life Coach")
    st.markdown("Web Search + File Search + Image Generation")
    st.markdown("---")
    st.markdown("**Try asking:**")
    st.markdown("- How am I doing on my fitness goals?")
    st.markdown("- Create a vision board for my 2025 goals")
    st.markdown("- I ran 5K today! Make me a celebration poster")
    reset = st.button("🗑️ Reset conversation")
    if reset:
        asyncio.run(session.clear_session())
        st.rerun()