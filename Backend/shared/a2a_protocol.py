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
    context:              dict                = {}
    # Serialised LangChain messages from the session store.
    # Each entry is {"type": "human"|"ai"|"tool", "content": "...", "name": "..." (tool only)}
    # Agents prepend these to their LangGraph state so the LLM has full context.
    conversation_history: list[dict]          = []


class A2AResponse(BaseModel):
    request_id:   str
    source_agent: AgentType
    status:       str           # "success" | "error" | "hitl_pending"
    result:       str
    metadata:     dict          = {}
    # New messages produced by this agent turn (AI reply + tool messages).
    # The orchestrator writes these back to the session store.
    new_messages: list[dict]    = []