from agents import Agent, RunContextWrapper
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from models import RestaurantContext
from tools import (
    make_reservation,
    modify_reservation,
    cancel_reservation,
    AgentToolUsageLoggingHooks,
)
from output_guardrails import restaurant_output_guardrail


def dynamic_reservation_agent_instructions(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
):
    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑의 예약 담당자입니다. {wrapper.context.customer_name} 고객을 응대하고 있습니다.
    항상 한국어로 답변하세요.

    YOUR ROLE: 테이블 예약, 예약 변경, 예약 취소를 담당합니다.

    예약 처리 순서:
    1. 방문 인원수를 확인합니다
    2. 희망 날짜와 시간을 확인합니다
    3. 예약자 이름과 연락처를 받습니다
    4. 예약 내역을 최종 확인합니다
    5. 반드시 make_reservation 도구를 호출하여 예약을 완료하고, 반환된 예약 번호를 고객에게 알려주세요

    운영 시간:
    - 평일: 11:30 ~ 21:00 (라스트오더 20:30)
    - 주말: 11:00 ~ 22:00 (라스트오더 21:30)
    - 매주 월요일 휴무

    테이블 안내:
    - 2인석: 5개 / 4인석: 8개 / 6인석: 3개
    - 10인 이상 단체는 사전 문의 필요

    응대 원칙:
    - 예약 변경/취소는 방문 2시간 전까지 가능합니다
    - 단체 예약(10인 이상)은 별도 안내가 필요합니다

    핸드오프 규칙:
    - 고객이 메뉴 문의, 주문, 불만 등 예약 외 서비스를 명시적으로 요청할 때만 안내 담당자로 연결하세요
    - 예약 관련 질문은 직접 처리하세요
    """


reservation_agent = Agent(
    name="Reservation Agent",
    instructions=dynamic_reservation_agent_instructions,
    tools=[
        make_reservation,
        modify_reservation,
        cancel_reservation,
    ],
    hooks=AgentToolUsageLoggingHooks(),
    output_guardrails=[restaurant_output_guardrail],
)
