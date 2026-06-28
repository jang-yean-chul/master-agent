from pydantic import BaseModel


class RestaurantContext(BaseModel):
    customer_name: str = "고객"
    table_number: int = 0
    visited_specialists: str = ""


class InputGuardRailOutput(BaseModel):
    is_off_topic: bool
    reason: str


class RestaurantOutputGuardRailOutput(BaseModel):
    is_inappropriate: bool
    reason: str
