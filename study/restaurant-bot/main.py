import dotenv

dotenv.load_dotenv()
from openai import OpenAI
import asyncio
import streamlit as st
from agents import Runner, SQLiteSession, InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered
from models import RestaurantContext
from my_agents.triage_agent import triage_agent

client = OpenAI()

restaurant_ctx = RestaurantContext(
    customer_name="고객",
    table_number=0,
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
                        st.write(message["content"][0]["text"].replace("$", "\$"))


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

            handoff_count = 0

            async for event in stream.stream_events():
                if event.type == "raw_response_event":

                    if event.data.type == "response.output_text.delta":
                        response += event.data.delta
                        text_placeholder.write(response.replace("$", "\$"))

                elif event.type == "agent_updated_stream_event":

                    if st.session_state["agent"].name != event.new_agent.name:

                        handoff_count += 1
                        if handoff_count > 4:
                            st.session_state["agent"] = triage_agent
                            text_placeholder.write("죄송합니다. 담당자 연결 중 문제가 발생했습니다. 다시 질문해 주세요.")
                            break

                        text_placeholder.write(f"🤖 {st.session_state['agent'].name}에서 {event.new_agent.name}(으)로 연결합니다...")

                        st.session_state["agent"] = event.new_agent

                        text_placeholder = st.empty()

                        st.session_state["text_placeholder"] = text_placeholder
                        response = ""

        except InputGuardrailTripwireTriggered:
            st.write("저는 레스토랑 관련 질문만 도와드릴 수 있어요. 메뉴 확인, 주문, 예약을 도와드릴게요.")

        except OutputGuardrailTripwireTriggered:
            st.write("죄송합니다. 응답을 다시 확인해 주시기 바랍니다. 다시 질문해 주세요.")
            st.session_state["text_placeholder"].empty()

message = st.chat_input(
    "무엇을 도와드릴까요?",
)

if message:

    if message:
        with st.chat_message("human"):
            st.write(message)
        asyncio.run(run_agent(message))


with st.sidebar:
    reset = st.button("대화 초기화")
    if reset:
        asyncio.run(session.clear_session())
        st.session_state["agent"] = triage_agent
    st.write(asyncio.run(session.get_items()))
