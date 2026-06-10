from pydantic import BaseModel
from enum import Enum
from typing import Optional


class AgentType(str, Enum):
    INTENT_DETECTOR = "intent_detector_agent"
    BILLING         = "billing"
    COMPLAINT       = "complaint"
    SALES           = "sales"


class A2ARequest(BaseModel):
    request_id:           str
    source_agent:         AgentType
    target_agent:         AgentType
    user_message:         str
    context:              dict       = {}
    conversation_history: list[dict] = []
    is_internal:          bool                  = False
    calling_agent:        Optional[str]         = None


class A2AResponse(BaseModel):
    request_id:   str
    source_agent: AgentType
    status:       str
    result:       str
    metadata:     dict          = {}
    new_messages: list[dict]    = []