import dotenv

dotenv.load_dotenv()
from openai import OpenAI
import asyncio
import streamlit as st
from agents import Runner, SQLiteSession, InputGuardrailTripwireTriggered
from models import RestaurantContext
from my_agents.triage_agent import triage_agent

client = OpenAI()

restaurant_ctx = RestaurantContext(
    customer_name="고객",
)

if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "chat-history",
        "restaurant-memory.db",
    )
session = st.session_state["session"]

if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent


async def paint_history():
    messages = await session.get_items()
    for message in messages:
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message["content"])
                else:
                    if message["type"] == "message":
                        for content_item in message["content"]:
                            if "text" in content_item:
                                st.write(content_item["text"].replace("$", "\\$"))


asyncio.run(paint_history())


async def run_agent(message):

    with st.chat_message("ai"):
        text_placeholder = st.empty()
        response = ""

        st.session_state["text_placeholder"] = text_placeholder

        try:

            stream = Runner.run_streamed(
                st.session_state["agent"],
                message,
                session=session,
                context=restaurant_ctx,
            )

            async for event in stream.stream_events():
                if event.type == "raw_response_event":

                    if event.data.type == "response.output_text.delta":
                        response += event.data.delta
                        text_placeholder.write(response.replace("$", "\\$"))

                elif event.type == "agent_updated_stream_event":

                    if st.session_state["agent"].name != event.new_agent.name:

                        agent_display_names = {
                            "Menu_Agent": "메뉴 전문가",
                            "Order_Agent": "주문 담당자",
                            "Reservation_Agent": "예약 담당자",
                            "Triage_Agent": "안내 담당자",
                        }
                        display_name = agent_display_names.get(event.new_agent.name, event.new_agent.name)
                        st.write(f"🤖 {display_name}에게 연결합니다...")

                        st.session_state["agent"] = event.new_agent

                        text_placeholder = st.empty()

                        st.session_state["text_placeholder"] = text_placeholder
                        response = ""

        except InputGuardrailTripwireTriggered:
            st.write("죄송합니다. 저는 레스토랑 관련 질문만 도와드릴 수 있어요.")


message = st.chat_input(
    "무엇을 도와드릴까요?",
)

if message:

    if "text_placeholder" in st.session_state:
        st.session_state["text_placeholder"].empty()

    if message:
        with st.chat_message("human"):
            st.write(message)
        asyncio.run(run_agent(message))


with st.sidebar:
    reset = st.button("대화 초기화")
    if reset:
        asyncio.run(session.clear_session())
    st.write(asyncio.run(session.get_items()))
