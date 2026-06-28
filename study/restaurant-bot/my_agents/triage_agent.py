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
from models import RestaurantContext, InputGuardRailOutput, HandoffData
from my_agents.menu_agent import menu_agent
from my_agents.order_agent import order_agent
from my_agents.reservation_agent import reservation_agent
from my_agents.complaints_agent import complaints_agent


input_guardrail_agent = Agent(
    name="Input Guardrail Agent",
    instructions="""
    사용자의 요청이 레스토랑과 관련된 것인지, 그리고 적절한지 판단하세요.

    허용 (is_off_topic=False):
    - 메뉴 질문, 음식 주문, 테이블 예약
    - 음식/서비스에 대한 불만 또는 피드백
    - 간단한 인사

    거부 (is_off_topic=True):
    - 레스토랑과 전혀 관련 없는 요청 (코딩, 날씨, 정치, 철학, 인생 등)
    - 욕설, 비속어, 폭력적이거나 위협적인 언어
    - 부적절하거나 공격적인 내용
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
    table_info = f"테이블 {wrapper.context.table_number}번" if wrapper.context.table_number else ""

    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑의 안내 담당자입니다. {wrapper.context.customer_name} 고객을 응대하고 있습니다.{" " + table_info if table_info else ""}
    항상 한국어로 답변하세요.

    YOUR MAIN JOB: 고객이 무엇을 원하는지 파악하고 적합한 전문 담당자에게 연결합니다.

    라우팅 가이드:

    🍽️ 메뉴 담당 (Menu Agent) - 아래 요청 시 연결:
    - 메뉴 추천 또는 문의
    - 재료, 알레르기 정보 확인
    - 채식/비건 메뉴 문의
    - 가격 문의
    - 오늘의 특별 메뉴

    📦 주문 담당 (Order Agent) - 아래 요청 시 연결:
    - 음식 주문
    - 주문 변경 또는 추가
    - 주문 취소

    📅 예약 담당 (Reservation Agent) - 아래 요청 시 연결:
    - 테이블 예약
    - 예약 변경 또는 취소
    - 단체 예약 문의

    😞 불만 담당 (Complaints Agent) - 아래 요청 시 연결:
    - 음식 맛, 품질에 대한 불만
    - 직원 서비스에 대한 불만
    - 환불 또는 보상 요청
    - 부정적인 경험 공유

    처리 순서:
    1. 고객의 요청을 파악합니다
    2. 적합한 담당자를 결정합니다
    3. 연결 전 적절한 안내 문구를 출력합니다
    4. 해당 에이전트로 핸드오프합니다

    요청이 불분명하면 1-2가지 질문으로 명확히 파악한 후 연결하세요.
    """


def handle_handoff(
    wrapper: RunContextWrapper[RestaurantContext],
    input_data: HandoffData,
):
    with st.sidebar:
        st.write(
            f"""
            Handing off to {input_data.to_agent_name}
            Reason: {input_data.reason}
            Issue Type: {input_data.issue_type}
            Description: {input_data.issue_description}
        """
        )


def make_handoff(agent):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,
        input_type=HandoffData,
        input_filter=handoff_filters.remove_all_tools,
    )


triage_agent = Agent(
    name="Triage Agent",
    instructions=dynamic_triage_agent_instructions,
    input_guardrails=[
        off_topic_guardrail,
    ],
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
        make_handoff(complaints_agent),
    ],
)


def make_specialist_to_triage_handoff(specialist_name: str):
    def on_handoff(wrapper: RunContextWrapper[RestaurantContext]):
        with st.sidebar:
            st.write(f"🔄 {specialist_name} → Triage Agent")

    return handoff(
        agent=triage_agent,
        on_handoff=on_handoff,
        input_filter=handoff_filters.remove_all_tools,
    )


menu_agent.handoffs = [make_specialist_to_triage_handoff("Menu Agent")]
order_agent.handoffs = [make_specialist_to_triage_handoff("Order Agent")]
reservation_agent.handoffs = [make_specialist_to_triage_handoff("Reservation Agent")]
complaints_agent.handoffs = [make_specialist_to_triage_handoff("Complaints Agent")]
