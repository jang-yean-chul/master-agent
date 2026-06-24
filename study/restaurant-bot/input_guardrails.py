from agents import (
    Agent,
    RunContextWrapper,
    input_guardrail,
    Runner,
    GuardrailFunctionOutput,
)
from models import RestaurantContext, InputGuardRailOutput


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
) -> GuardrailFunctionOutput:
    result = await Runner.run(
        input_guardrail_agent,
        input,
        context=wrapper.context,
    )
    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_off_topic,
    )
