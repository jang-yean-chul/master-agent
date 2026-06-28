from agents import (
    Agent,
    output_guardrail,
    Runner,
    RunContextWrapper,
    GuardrailFunctionOutput,
)
from models import RestaurantOutputGuardRailOutput, RestaurantContext


restaurant_output_guardrail_agent = Agent(
    name="Restaurant Output Guardrail",
    instructions="""
    레스토랑 직원의 응답이 적절한지 판단하세요.

    부적절한 응답 (is_inappropriate=True):
    - 비전문적이거나 무례한 언어 사용
    - 내부 운영 정보나 원가 정보 노출
    - 권한 밖의 과도한 약속 (예: 무조건 전액 환불 보장)
    - 다른 레스토랑이나 경쟁업체 비교/비방
    - 고객을 차별하거나 모욕하는 내용

    적절한 응답 (is_inappropriate=False):
    - 정중하고 전문적인 언어
    - 메뉴, 주문, 예약, 불만 처리 관련 내용
    - 고객에게 도움이 되는 정보 제공
""",
    output_type=RestaurantOutputGuardRailOutput,
)


@output_guardrail
async def restaurant_output_guardrail(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent,
    output: str,
):
    result = await Runner.run(
        restaurant_output_guardrail_agent,
        output,
        context=wrapper.context,
    )

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_inappropriate,
    )
