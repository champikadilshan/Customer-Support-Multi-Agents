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
    # Serialised LangChain messages — agents prepend these to LangGraph state.
    conversation_history: list[dict] = []
    # Internal call flags — set by make_agent_call_tool, never by the orchestrator.
    # is_internal=True suppresses greetings, HITL, and further inter-agent calls.
    is_internal:          bool                  = False
    calling_agent:        Optional[str]         = None   # AgentType.value string


class A2AResponse(BaseModel):
    request_id:   str
    source_agent: AgentType
    status:       str           # "success" | "error" | "hitl_pending"
    result:       str
    metadata:     dict          = {}
    # New messages produced this turn — orchestrator writes back to session store.
    new_messages: list[dict]    = []