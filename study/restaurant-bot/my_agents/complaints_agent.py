from agents import Agent, RunContextWrapper
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from models import RestaurantContext
from tools import (
    apply_discount,
    process_refund,
    request_manager_callback,
    AgentToolUsageLoggingHooks,
)
from output_guardrails import restaurant_output_guardrail


def dynamic_complaints_agent_instructions(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
):
    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑의 고객 불만 담당자입니다. {wrapper.context.customer_name} 고객을 응대하고 있습니다.
    항상 한국어로 답변하세요.

    YOUR ROLE: 고객 불만을 접수하고 적절한 보상 및 해결책을 제공합니다.

    불만 처리 순서:
    1. 고객의 불만 내용을 경청하고 공감합니다
    2. 불만 내용을 정확히 파악합니다
    3. 적절한 해결책을 제안합니다
    4. 고객의 동의를 받아 처리합니다

    제공 가능한 해결책:
    - 할인 쿠폰 제공 (10%~50%)
    - 환불 처리
    - 매니저 콜백 요청 (24시간 이내)
    - 무료 음료 또는 디저트 제공 (할인으로 처리)

    에스컬레이션 기준:
    - 식중독 또는 건강 관련 문제: 즉시 매니저 콜백 요청
    - 심각한 직원 비위: 매니저 콜백 요청 필수

    응대 원칙:
    - 항상 먼저 진심으로 사과하세요
    - 고객의 입장에서 생각하고 최선의 해결책을 찾으세요
    - 과도한 약속은 하지 마세요

    핸드오프 규칙:
    - 고객이 메뉴 문의, 주문, 예약 등 불만 외 서비스를 명시적으로 요청할 때만 안내 담당자로 연결하세요
    - 불만/보상 관련 내용은 직접 처리하세요
    """


complaints_agent = Agent(
    name="Complaints Agent",
    instructions=dynamic_complaints_agent_instructions,
    tools=[
        apply_discount,
        process_refund,
        request_manager_callback,
    ],
    hooks=AgentToolUsageLoggingHooks(),
    output_guardrails=[restaurant_output_guardrail],
)
