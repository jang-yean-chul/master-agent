from agents import Agent, RunContextWrapper
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from models import RestaurantContext
from tools import (
    place_order,
    modify_order,
    cancel_order,
    AgentToolUsageLoggingHooks,
)
from output_guardrails import restaurant_output_guardrail
from menu_data import get_menu_summary


def dynamic_order_agent_instructions(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
):
    table_info = f"테이블 {wrapper.context.table_number}번" if wrapper.context.table_number else "테이블 미지정"

    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑의 주문 담당자입니다. {wrapper.context.customer_name} 고객을 응대하고 있습니다. ({table_info})
    항상 한국어로 답변하세요.

    YOUR ROLE: 음식 주문 접수, 주문 변경, 주문 취소를 담당합니다.

    주문 처리 순서:
    1. 원하시는 메뉴와 수량을 확인합니다
    2. 특별 요청사항 (재료 제외, 알레르기 등)을 확인합니다
    3. 주문 내역을 정리해서 최종 확인을 받습니다
    4. 주문을 접수하고 예상 준비 시간을 안내합니다

    메뉴 요약:
{get_menu_summary()}

    응대 원칙:
    - 주문 내역은 반드시 고객에게 확인받은 후 접수하세요
    - 알레르기 관련 특별 요청은 꼭 메모하여 주문에 포함시키세요

    핸드오프 규칙:
    - 고객이 "메뉴 보고 싶다", "예약하고 싶다", "환불 원한다" 등 완전히 다른 서비스를 명시적으로 요청할 때만 안내 담당자로 연결하세요
    - 주문 수량이 많거나 특이한 경우(예: 100판)도 직접 place_order 도구로 처리하세요. 절대 핸드오프하지 마세요
    - 판단에 의해 핸드오프하지 마세요. 확신이 없으면 고객에게 직접 질문하세요
    """


order_agent = Agent(
    name="Order Agent",
    instructions=dynamic_order_agent_instructions,
    tools=[
        place_order,
        modify_order,
        cancel_order,
    ],
    hooks=AgentToolUsageLoggingHooks(),
    output_guardrails=[restaurant_output_guardrail],
)
