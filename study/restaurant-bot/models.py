from pydantic import BaseModel


class RestaurantContext(BaseModel):
    customer_name: str = "고객"
    last_specialist: str = ""


class InputGuardRailOutput(BaseModel):
    is_off_topic: bool
    reason: str


class HandoffData(BaseModel):
    to_agent_name: str
    issue_type: str
    issue_description: str
    reason: str


class OutputGuardRailOutput(BaseModel):
    is_inappropriate: bool
    reason: str
