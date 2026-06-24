import streamlit as st
from agents import (
    Agent,
    RunContextWrapper,
    handoff,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions import handoff_filters
from models import RestaurantContext
from input_guardrails import off_topic_guardrail
from my_agents.menu_agent import menu_agent
from my_agents.order_agent import order_agent
from my_agents.reservation_agent import reservation_agent
from my_agents.complaints_agent import complaints_agent


def dynamic_triage_agent_instructions(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
):
    avoid_note = ""
    if wrapper.context.last_specialist:
        avoid_note = f"\n    ⚠️ 방금 {wrapper.context.last_specialist}에서 이 대화가 넘어왔습니다. 절대 {wrapper.context.last_specialist}로 다시 라우팅하지 마세요. 다른 에이전트로 연결하거나, 고객에게 직접 안내하세요."

    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑의 안내 담당자입니다. {wrapper.context.customer_name} 고객을 응대하고 있습니다.
    항상 한국어로 답변하세요.

    YOUR MAIN JOB: 고객이 무엇을 원하는지 파악하고 적합한 전문 담당자에게 연결합니다.

    라우팅 가이드:

    메뉴 에이전트 (Menu_Agent) - 아래 요청 시 연결:
    - 메뉴 추천 또는 문의
    - 재료, 알레르기 정보 확인
    - 채식/비건 메뉴 문의
    - 가격 문의

    주문 에이전트 (Order_Agent) - 아래 요청 시 연결:
    - 음식 주문
    - 주문 변경 또는 추가

    예약 에이전트 (Reservation_Agent) - 아래 요청 시 연결:
    - 테이블 예약
    - 예약 변경 또는 취소
    - 단체 예약 문의

    불만 에이전트 (Complaints_Agent) - 아래 요청 시 연결:
    - 음식 맛, 품질에 대한 불만
    - 직원 서비스에 대한 불만
    - 환불 또는 보상 요청
    - 부정적인 경험 공유

    처리 순서:
    1. 고객의 요청을 파악합니다
    2. 적합한 담당자를 결정합니다
    3. 연결 전 적절한 안내 문구를 출력합니다 (예: 메뉴 문의라면 "메뉴 전문가에게 연결해 드릴게요!", 예약이라면 "예약 담당자에게 연결해 드릴게요!")
    4. 해당 에이전트로 핸드오프합니다

    요청이 불분명하면 1-2가지 질문으로 명확히 파악한 후 연결하세요.
    {avoid_note}
    """


def make_handoff(agent):
    def on_handoff_to_specialist(wrapper: RunContextWrapper[RestaurantContext]):
        wrapper.context.last_specialist = ""
        with st.sidebar:
            st.write(f"Triage → {agent.name}")

    return handoff(
        agent=agent,
        on_handoff=on_handoff_to_specialist,
        input_filter=handoff_filters.remove_all_tools,
    )


triage_agent = Agent(
    name="Triage_Agent",
    instructions=dynamic_triage_agent_instructions,
    input_guardrails=[off_topic_guardrail],
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
        make_handoff(complaints_agent),
    ],
)


def make_specialist_to_triage_handoff(specialist_name: str):
    def on_specialist_handoff(wrapper: RunContextWrapper[RestaurantContext]):
        wrapper.context.last_specialist = specialist_name
        with st.sidebar:
            st.write(f"{specialist_name} → Triage_Agent")

    return handoff(
        agent=triage_agent,
        on_handoff=on_specialist_handoff,
        input_filter=handoff_filters.remove_all_tools,
    )


# 전문 에이전트 → Triage Agent 단방향 핸드오프 + 모든 에이전트에 input guardrail 적용
menu_agent.handoffs = [make_specialist_to_triage_handoff("Menu_Agent")]
order_agent.handoffs = [make_specialist_to_triage_handoff("Order_Agent")]
reservation_agent.handoffs = [make_specialist_to_triage_handoff("Reservation_Agent")]
complaints_agent.handoffs = [make_specialist_to_triage_handoff("Complaints_Agent")]

menu_agent.input_guardrails = [off_topic_guardrail]
order_agent.input_guardrails = [off_topic_guardrail]
reservation_agent.input_guardrails = [off_topic_guardrail]
complaints_agent.input_guardrails = [off_topic_guardrail]
