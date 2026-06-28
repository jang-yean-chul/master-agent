import streamlit as st
from agents import function_tool, AgentHooks, Agent, Tool, RunContextWrapper
from models import RestaurantContext
from menu_data import MENUS, CATEGORY_NAMES, ALLERGENS, get_menu_by_category
import random
from datetime import datetime, timedelta


# =============================================================================
# 메뉴 안내 TOOLS
# =============================================================================


@function_tool
def get_menu_info(context: RestaurantContext, category: str) -> str:
    """
    카테고리별 메뉴 정보를 조회합니다.

    Args:
        category: 메뉴 카테고리 (애피타이저/메인/디저트/음료/전체)
    """
    if category in ["전체", "all"]:
        result = "📋 전체 메뉴\n"
        for cat_key, items in MENUS.items():
            cat_name = CATEGORY_NAMES[cat_key]
            result += f"\n**{cat_name}**\n"
            result += "\n".join(f"{item['emoji']} {item['name']} {item['price']:,}원" for item in items) + "\n"
        return result

    return get_menu_by_category(category)


@function_tool
def check_allergen_info(context: RestaurantContext, menu_item: str) -> str:
    """
    메뉴 아이템의 알레르기 정보를 조회합니다.

    Args:
        menu_item: 알레르기 정보를 확인할 메뉴 이름
    """
    for key, allergens in ALLERGENS.items():
        if menu_item.lower() in key.lower() or key.lower() in menu_item.lower():
            if allergens:
                return f"⚠️ **{key}** 알레르기 정보:\n포함 성분: {', '.join(allergens)}"
            else:
                return f"✅ **{key}**: 주요 알레르기 유발 성분 없음"

    return f"'{menu_item}'의 알레르기 정보를 찾을 수 없습니다. 직접 주방에 문의해 드릴까요?"


@function_tool
def get_daily_specials(context: RestaurantContext) -> str:
    """
    오늘의 특별 메뉴를 조회합니다.
    """
    specials = [
        ("🍝 오늘의 파스타: 버섯 트러플 파스타", "18,000원 → 14,000원"),
        ("🍕 오늘의 피자: 4치즈 피자", "19,000원 → 15,000원"),
        ("🍷 오늘의 와인: 키안티 (보틀)", "45,000원 → 35,000원"),
    ]

    today = datetime.now().strftime("%Y년 %m월 %d일")
    result = f"🌟 **{today} 오늘의 특별 메뉴**\n\n"
    for item, price in specials:
        result += f"{item}\n   {price}\n\n"
    result += "※ 오늘의 메뉴는 재고 소진 시 종료됩니다."
    return result


# =============================================================================
# 주문 TOOLS
# =============================================================================


@function_tool
def place_order(context: RestaurantContext, items: str, special_requests: str = "") -> str:
    """
    음식을 주문합니다.

    Args:
        items: 주문할 메뉴와 수량 (예: "토마토 파스타 1개, 마르게리타 피자 1개")
        special_requests: 특별 요청사항 (예: "파스타 소금 적게")
    """
    order_id = f"ORD-{random.randint(10000, 99999)}"
    prep_time = random.randint(15, 25)

    return f"""
✅ 주문이 접수되었습니다!
📋 주문 번호: {order_id}
🍽️ 주문 내역: {items}
💬 특별 요청: {special_requests if special_requests else "없음"}
🪑 테이블: {context.table_number if context.table_number else "미지정"}
⏱️ 예상 준비 시간: {prep_time}분
    """.strip()


@function_tool
def modify_order(context: RestaurantContext, order_id: str, changes: str) -> str:
    """
    기존 주문을 변경합니다.

    Args:
        order_id: 변경할 주문 번호
        changes: 변경 내용 (예: "크림 파스타 추가, 마르게리타 피자 취소")
    """
    return f"""
✅ 주문이 변경되었습니다!
📋 주문 번호: {order_id}
🔄 변경 내용: {changes}
⏱️ 변경 사항이 주방에 전달되었습니다.
    """.strip()


@function_tool
def cancel_order(context: RestaurantContext, order_id: str, reason: str) -> str:
    """
    주문을 취소합니다.

    Args:
        order_id: 취소할 주문 번호
        reason: 취소 사유
    """
    return f"""
✅ 주문이 취소되었습니다.
📋 주문 번호: {order_id}
📝 취소 사유: {reason}
💳 결제하신 금액은 영업일 기준 3~5일 내 환불됩니다.
    """.strip()


# =============================================================================
# 예약 TOOLS
# =============================================================================


@function_tool
def make_reservation(
    context: RestaurantContext,
    date: str,
    time: str,
    party_size: int,
    name: str,
    phone: str,
) -> str:
    """
    테이블을 예약합니다.

    Args:
        date: 예약 날짜 (예: 2026-07-01)
        time: 예약 시간 (예: 18:30)
        party_size: 방문 인원수
        name: 예약자 이름
        phone: 연락처
    """
    reservation_id = f"RES-{random.randint(10000, 99999)}"

    return f"""
✅ 예약이 완료되었습니다!
🔗 예약 번호: {reservation_id}
📅 날짜/시간: {date} {time}
👥 인원: {party_size}명
👤 예약자: {name}
📞 연락처: {phone}
방문을 기다리겠습니다! 예약 변경/취소는 방문 2시간 전까지 가능합니다.
    """.strip()


@function_tool
def modify_reservation(context: RestaurantContext, reservation_id: str, changes: str) -> str:
    """
    기존 예약을 변경합니다.

    Args:
        reservation_id: 변경할 예약 번호
        changes: 변경 내용 (예: "날짜를 7월 2일로, 인원 4명으로 변경")
    """
    return f"""
✅ 예약이 변경되었습니다!
🔗 예약 번호: {reservation_id}
🔄 변경 내용: {changes}
📱 변경 확인 문자가 발송되었습니다.
    """.strip()


@function_tool
def cancel_reservation(context: RestaurantContext, reservation_id: str) -> str:
    """
    예약을 취소합니다.

    Args:
        reservation_id: 취소할 예약 번호
    """
    return f"""
✅ 예약이 취소되었습니다.
🔗 예약 번호: {reservation_id}
📱 취소 확인 문자가 발송되었습니다.
다음에 다시 방문해 주세요. 감사합니다.
    """.strip()


# =============================================================================
# 불만 처리 TOOLS
# =============================================================================


@function_tool
def apply_discount(context: RestaurantContext, discount_rate: int, reason: str) -> str:
    """
    불만 보상으로 할인을 적용합니다.

    Args:
        discount_rate: 할인율 (10~50 사이 정수, %)
        reason: 할인 사유
    """
    discount_code = f"DISC-{random.randint(1000, 9999)}"

    return f"""
🎁 할인이 적용되었습니다!
💰 할인율: {discount_rate}%
📝 사유: {reason}
🎟️ 할인 코드: {discount_code}
⏰ 유효 기간: 다음 방문 시까지
불편을 드려 죄송합니다. 더 나은 서비스로 보답하겠습니다.
    """.strip()


@function_tool
def process_refund(context: RestaurantContext, amount: int, reason: str) -> str:
    """
    환불을 처리합니다.

    Args:
        amount: 환불 금액 (원)
        reason: 환불 사유
    """
    refund_id = f"REF-{random.randint(100000, 999999)}"

    return f"""
✅ 환불 요청이 처리되었습니다.
🔗 환불 번호: {refund_id}
💰 환불 금액: {amount:,}원
📝 사유: {reason}
⏱️ 처리 기간: 영업일 기준 3~5일
💳 결제하신 카드로 환불됩니다.
    """.strip()


@function_tool
def request_manager_callback(context: RestaurantContext, issue_summary: str) -> str:
    """
    매니저 콜백을 요청합니다.

    Args:
        issue_summary: 불만 내용 요약
    """
    ticket_id = f"MGR-{random.randint(1000, 9999)}"

    return f"""
📞 매니저 콜백이 요청되었습니다.
🎫 접수 번호: {ticket_id}
📝 내용: {issue_summary}
⏰ 연락 예정: 24시간 이내
불편을 드려 진심으로 사과드립니다.
    """.strip()


# =============================================================================
# HOOKS
# =============================================================================


class AgentToolUsageLoggingHooks(AgentHooks):

    async def on_tool_start(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        tool: Tool,
    ):
        with st.sidebar:
            st.write(f"🔧 **{agent.name}** starting tool: `{tool.name}`")

    async def on_tool_end(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        tool: Tool,
        result: str,
    ):
        with st.sidebar:
            st.write(f"🔧 **{agent.name}** used tool: `{tool.name}`")
            st.code(result)

    async def on_handoff(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        source: Agent[RestaurantContext],
    ):
        with st.sidebar:
            st.write(f"🔄 Handoff: **{source.name}** → **{agent.name}**")

    async def on_start(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
    ):
        with st.sidebar:
            st.write(f"🚀 **{agent.name}** activated")

    async def on_end(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        output,
    ):
        with st.sidebar:
            st.write(f"🏁 **{agent.name}** completed")
