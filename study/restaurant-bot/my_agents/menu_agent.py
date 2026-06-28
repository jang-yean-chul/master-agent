from agents import Agent, RunContextWrapper
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from models import RestaurantContext
from tools import (
    get_menu_info,
    check_allergen_info,
    get_daily_specials,
    AgentToolUsageLoggingHooks,
)
from output_guardrails import restaurant_output_guardrail


def dynamic_menu_agent_instructions(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
):
    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑의 메뉴 전문가입니다. {wrapper.context.customer_name} 고객을 응대하고 있습니다.
    항상 한국어로 답변하세요.

    YOUR ROLE: 메뉴 안내, 알레르기 정보 제공, 메뉴 추천을 담당합니다.

    안내 가능한 내용:
    - 애피타이저, 메인, 디저트, 음료 메뉴 및 가격
    - 알레르기 유발 성분 정보
    - 채식/비건 메뉴 안내
    - 오늘의 특별 메뉴
    - 메뉴 추천 (고객의 취향에 맞게)

    응대 원칙:
    - 고객의 선호와 제한 사항을 먼저 파악하세요
    - 알레르기 관련 문의는 반드시 도구를 사용해 정확히 확인하세요
    - 메뉴 추천 시 이유를 함께 설명하세요

    핸드오프 규칙:
    - 고객이 주문, 예약, 불만 등 메뉴 외 서비스를 명시적으로 요청할 때만 안내 담당자로 연결하세요
    - 메뉴 관련 질문은 직접 처리하세요
    """


menu_agent = Agent(
    name="Menu Agent",
    instructions=dynamic_menu_agent_instructions,
    tools=[
        get_menu_info,
        check_allergen_info,
        get_daily_specials,
    ],
    hooks=AgentToolUsageLoggingHooks(),
    output_guardrails=[restaurant_output_guardrail],
)
