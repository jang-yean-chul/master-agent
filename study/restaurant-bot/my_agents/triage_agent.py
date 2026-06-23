import streamlit as st
from agents import (
    Agent,
    RunContextWrapper,
    input_guardrail,
    Runner,
    GuardrailFunctionOutput,
    handoff,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions import handoff_filters
from models import RestaurantContext, InputGuardRailOutput
from my_agents.menu_agent import menu_agent
from my_agents.order_agent import order_agent
from my_agents.reservation_agent import reservation_agent


input_guardrail_agent = Agent(
    name="Input Guardrail Agent",
    instructions="""
    사용자의 요청이 레스토랑과 관련된 것인지 판단하세요. 메뉴 질문, 음식 주문, 테이블 예약은 허용됩니다.
    간단한 인사도 허용됩니다.
    레스토랑과 전혀 관련 없는 요청(코딩 도움, 날씨, 정치 등)은 off-topic으로 표시하세요.
""",
    output_type=InputGuardRailOutput,
)


@input_guardrail
async def off_topic_guardrail(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
    input: str,
):
    result = await Runner.run(
        input_guardrail_agent,
        input,
        context=wrapper.context,
    )

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_off_topic,
    )


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
        wrapper.context.last_specialist = ""  # Triage→전문 핸드오프 시 last_specialist 초기화
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
    input_guardrails=[
        off_topic_guardrail,
    ],
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
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


# 전문 에이전트 → Triage Agent 단방향 핸드오프 (순환 참조 방지를 위해 여기서 일괄 설정)
menu_agent.handoffs = [make_specialist_to_triage_handoff("Menu_Agent")]
order_agent.handoffs = [make_specialist_to_triage_handoff("Order_Agent")]
reservation_agent.handoffs = [make_specialist_to_triage_handoff("Reservation_Agent")]

