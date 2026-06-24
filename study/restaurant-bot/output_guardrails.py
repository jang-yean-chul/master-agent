from agents import (
    Agent,
    output_guardrail,
    Runner,
    RunContextWrapper,
    GuardrailFunctionOutput,
)
from models import RestaurantContext, OutputGuardRailOutput


output_guardrail_agent = Agent(
    name="Output Guardrail Agent",
    instructions="""
    레스토랑 챗봇의 응답이 적절한지 검토하세요.

    부적절한 응답 (is_inappropriate=True):
    - 비전문적이거나 무례한 언어
    - 내부 운영 정보 노출 (직원 개인정보, 원가, 내부 시스템 정보 등)
    - 권한 밖의 과도한 약속 (예: 무조건 전액 환불 보장 등)
    - 법적으로 문제가 될 수 있는 발언

    적절한 응답 (is_inappropriate=False):
    - 정중하고 전문적인 언어
    - 메뉴, 주문, 예약, 불만 처리 관련 내용
    - 고객에게 실질적으로 도움이 되는 내용
""",
    output_type=OutputGuardRailOutput,
)


@output_guardrail
async def professional_response_guardrail(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent,
    output: str,
) -> GuardrailFunctionOutput:
    result = await Runner.run(
        output_guardrail_agent,
        output,
        context=wrapper.context,
    )
    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_inappropriate,
    )
