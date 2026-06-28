MENUS = {
    "appetizer": [
        {"name": "시저 샐러드", "price": 9000, "emoji": "🥗"},
        {"name": "그린 샐러드", "price": 8000, "emoji": "🥗"},
        {"name": "양파 수프", "price": 7000, "emoji": "🍲"},
        {"name": "치즈 플래터", "price": 12000, "emoji": "🧀"},
    ],
    "main": [
        {"name": "토마토 파스타", "price": 12000, "emoji": "🍝"},
        {"name": "크림 파스타", "price": 13000, "emoji": "🍝"},
        {"name": "채식 파스타", "price": 12000, "emoji": "🍝"},
        {"name": "마르게리타 피자", "price": 15000, "emoji": "🍕"},
        {"name": "페퍼로니 피자", "price": 17000, "emoji": "🍕"},
        {"name": "채소 피자", "price": 15000, "emoji": "🍕"},
    ],
    "dessert": [
        {"name": "티라미수", "price": 8000, "emoji": "🍰"},
        {"name": "판나코타", "price": 7000, "emoji": "🍮"},
        {"name": "젤라또", "price": 6000, "emoji": "🍦"},
    ],
    "drink": [
        {"name": "탄산음료", "price": 3000, "emoji": "🥤"},
        {"name": "주스", "price": 4000, "emoji": "🧃"},
        {"name": "커피", "price": 4500, "emoji": "☕"},
        {"name": "와인 (글라스)", "price": 9000, "emoji": "🍷"},
    ],
}

CATEGORY_NAMES = {
    "appetizer": "애피타이저",
    "main": "메인",
    "dessert": "디저트",
    "drink": "음료",
}

ALLERGENS = {
    "토마토 파스타": ["글루텐 (밀)", "달걀"],
    "크림 파스타": ["글루텐 (밀)", "달걀", "유제품"],
    "채식 파스타": ["글루텐 (밀)", "달걀"],
    "마르게리타 피자": ["글루텐 (밀)", "유제품"],
    "페퍼로니 피자": ["글루텐 (밀)", "유제품"],
    "채소 피자": ["글루텐 (밀)", "유제품"],
    "시저 샐러드": ["달걀", "생선 (앤초비)", "유제품"],
    "그린 샐러드": [],
    "티라미수": ["글루텐 (밀)", "달걀", "유제품"],
    "판나코타": ["유제품"],
}


def get_menu_summary() -> str:
    lines = []
    for cat_key, items in MENUS.items():
        cat_name = CATEGORY_NAMES[cat_key]
        for item in items:
            lines.append(f"- {item['name']} {item['price']:,}원")
    return "\n".join(lines)


def get_menu_by_category(category: str) -> str:
    cat_key = {v: k for k, v in CATEGORY_NAMES.items()}.get(category, category)
    items = MENUS.get(cat_key)
    if not items:
        return f"'{category}' 카테고리를 찾을 수 없습니다. 애피타이저/메인/디저트/음료 중 하나를 입력해주세요."
    cat_name = CATEGORY_NAMES.get(cat_key, category)
    lines = [f"📋 {cat_name} 메뉴"] + [f"{item['emoji']} {item['name']} {item['price']:,}원" for item in items]
    return "\n".join(lines)
