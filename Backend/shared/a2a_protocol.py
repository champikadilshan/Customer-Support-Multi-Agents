from pydantic import BaseModel
from enum import Enum


class AgentType(str, Enum):
    INTENT_DETECTOR = "intent_detector_agent"
    BILLING = "billing"
    COMPLAINT = "complaint"
    SALES = "sales"


class A2ARequest(BaseModel):
    request_id: str
    source_agent: AgentType
    target_agent: AgentType
    user_message: str
    context: dict = {}


class A2AResponse(BaseModel):
    request_id: str
    source_agent: AgentType
    status: str  # "success" | "error"
    result: str
    metadata: dict = {}