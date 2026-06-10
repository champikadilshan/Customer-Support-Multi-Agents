import uuid
import json
import httpx
import sys
import os
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel
from typing import TypedDict, Literal, AsyncIterator, Optional
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import AGENT_URLS, INTENT_DETECTOR_PORT
from shared.llm import get_vertex_llm
from shared.session_store import session_store
from shared.message_utils import messages_to_dicts, dicts_to_messages
from shared.trace_emitter import trace_emitter

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

VALID_INTENTS = {"billing", "complaint", "sales"}

AGENT_TYPE_MAP: dict[str, AgentType] = {
    "billing":   AgentType.BILLING,
    "complaint": AgentType.COMPLAINT,
    "sales":     AgentType.SALES,
}


class OrchestratorState(TypedDict):
    user_message:         str
    conversation_history: list[dict]   # serialised prior messages for context
    detected_intent:      str
    target_agent:         AgentType
    a2a_response:         str
    request_id:           str
    final_response:       str

llm = get_vertex_llm(temperature=0)

class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None   # client sends this on follow-up turns

class SessionResetRequest(BaseModel):
    session_id: str

def _history_text(history: list[dict]) -> str:
    lines = []

    for msg in history:
        t = msg.get("type", "")
        c = msg.get("content", "")
        if t == "human" and c:
            lines.append(f"User: {c}")
        elif t == "ai" and c:
            lines.append(f"Agent: {c}")

    return "\n".join(lines)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def detect_intent_node(state: OrchestratorState) -> OrchestratorState:
    history_block = _history_text(state["conversation_history"])
    history_section = ( f"\n\nConversation so far:\n{history_block}" if history_block else "" )

    prompt = f"""You are an intent classifier for a customer support system.
Classify the following user message into EXACTLY one of these categories:
- billing   (invoices, payments, charges, account balance)
- complaint (issues, problems, bad experience, refund requests, raise a ticket)
- sales     (product info, pricing, promotions, purchasing){history_section}

Current user message: {state['user_message']}

Reply with ONLY the single word label. Nothing else."""

    intent = llm.invoke(prompt).content.strip().lower()

    if intent not in VALID_INTENTS:
        intent = "unknown"

    return {
        **state,
        "detected_intent": intent,
        "target_agent":    AGENT_TYPE_MAP.get(intent, AgentType.BILLING),
        "request_id":      str(uuid.uuid4()),
    }


async def dispatch_to_agent_node(state: OrchestratorState) -> OrchestratorState:
    req = A2ARequest(
        request_id=state["request_id"],
        source_agent=AgentType.INTENT_DETECTOR,
        target_agent=state["target_agent"],
        user_message=state["user_message"],
        context={"detected_intent": state["detected_intent"]},
        conversation_history=state["conversation_history"],
    )

    try:
        async with httpx.AsyncClient() as client:
            url = AGENT_URLS[state["target_agent"]]
            response = await client.post(url, json=req.model_dump(), timeout=30.0)
            response.raise_for_status()
            a2a_resp = A2AResponse(**response.json())
            return {**state, "a2a_response": a2a_resp.result}

    except httpx.ConnectError:
        agent_name = state["target_agent"].value
        return {
            **state,
            "a2a_response": (
                f"The {agent_name} agent is currently unavailable. "
                "Please try again later."
            ),
        }

    except httpx.TimeoutException:
        agent_name = state["target_agent"].value
        return {
            **state,
            "a2a_response": (
                f"The {agent_name} agent took too long to respond. "
                "Please try again."
            ),
        }

    except httpx.HTTPStatusError as e:
        agent_name = state["target_agent"].value
        return {
            **state,
            "a2a_response": (
                f"The {agent_name} agent returned an error "
                f"(status {e.response.status_code}). Please try again."
            ),
        }


def format_response_node(state: OrchestratorState) -> OrchestratorState:
    agent_label = {
        AgentType.BILLING:   "Billing Support",
        AgentType.COMPLAINT: "Complaint Support",
        AgentType.SALES:     "Sales Support",
    }.get(state["target_agent"], "Support")

    final = f"[{agent_label}]\n\n{state['a2a_response']}"

    return {**state, "final_response": final}


def unknown_intent_node(state: OrchestratorState) -> OrchestratorState:
    return {
        **state,
        "final_response": (
            "I'm sorry, I couldn't understand your request. "
            "Please ask about billing, a complaint, or our products."
        ),
    }


def route_intent(state: OrchestratorState) -> Literal["dispatch", "unknown_intent"]:
    return "dispatch" if state["detected_intent"] in VALID_INTENTS else "unknown_intent"


def build_orchestrator_graph() -> CompiledStateGraph:
    graph = StateGraph(OrchestratorState)

    graph.add_node("detect_intent",   detect_intent_node)
    graph.add_node("dispatch",        dispatch_to_agent_node)
    graph.add_node("format_response", format_response_node)
    graph.add_node("unknown_intent",  unknown_intent_node)

    graph.set_entry_point("detect_intent")

    graph.add_conditional_edges(
        "detect_intent",
        route_intent,
        {
            "dispatch":       "dispatch",
            "unknown_intent": "unknown_intent",
        },
    )

    graph.add_edge("dispatch",        "format_response")
    graph.add_edge("format_response", END)
    graph.add_edge("unknown_intent",  END)

    return graph.compile()


_CONFIRMATION_STARTERS = { "yes", "no", "ok", "okay", "sure", "yep", "nope", "yeah", "nah", "confirm", "cancel", "please", "go ahead", "do it", "skip", "don't", "dont",}
_SALES_KEYWORDS    = {"plan", "plans", "product", "fiber", "internet", "mobile", "tv", "bundle", "price", "pricing", "upgrade", "promotion", "deal", "offer", "buy", "purchase", "available"}
_BILLING_KEYWORDS  = {"bill", "invoice", "charge", "payment", "balance", "pay", "owe", "statement", "account"}
_COMPLAINT_KEYWORDS = {"ticket", "complaint", "issue", "problem", "outage", "refund", "broken", "not working", "check ticket",  "check complaint", "ticket number", "ticket status"}

_DOMAIN_KEYWORDS: dict[AgentType, set] = {
    AgentType.SALES:     _SALES_KEYWORDS,
    AgentType.BILLING:   _BILLING_KEYWORDS,
    AgentType.COMPLAINT: _COMPLAINT_KEYWORDS,
}


def _is_mixed_intent(message: str, active_agent: AgentType) -> bool:
    words = set(message.lower().split())

    primary_keywords   = _DOMAIN_KEYWORDS.get(active_agent, set())
    has_primary        = bool(words & primary_keywords)

    other_domains = [a for a in _DOMAIN_KEYWORDS if a != active_agent]
    has_secondary  = any(bool(words & _DOMAIN_KEYWORDS[a]) for a in other_domains)

    result = has_primary and has_secondary
    print(f"[MIXED_INTENT] active={active_agent.value} has_primary={has_primary} "
          f"has_secondary={has_secondary} result={result}")

    return result


def _is_confirmation(message: str) -> bool:
    cleaned = message.lower().strip().rstrip(".,!?")
    words   = cleaned.split()

    if not words:
        return False

    if words[0] in _CONFIRMATION_STARTERS:
        return True

    if len(words) <= 4 and set(words) & _CONFIRMATION_STARTERS:
        return True

    return False


async def _run_chat( user_message: str, session_id:   Optional[str],) -> tuple[dict, str]:
    sess = session_store.get_or_create(session_id)
    sid  = sess.session_id

    history      = session_store.get_messages(sid)
    active_agent = session_store.get_active_agent(sid)

    pending_handoff = session_store.get_metadata(sid, "pending_handoff")

    if pending_handoff and pending_handoff in AGENT_TYPE_MAP:
        previous_agent = active_agent.value if active_agent else "unknown"
        new_agent      = AGENT_TYPE_MAP[pending_handoff]
        session_store.set_active_agent(sid, new_agent)
        session_store.set_metadata(sid, "pending_handoff", None)
        active_agent = new_agent
        request_id   = str(uuid.uuid4())
        intent       = pending_handoff
        trace_emitter.emit(sid, "handoff_executed",
                           from_agent=previous_agent,
                           to_agent=pending_handoff,
                           request_id=request_id,
                           reason="pending_handoff consumed — routing forced to new agent")
        session_store.append_messages(sid, [{"type": "human", "content": user_message}])
        history = session_store.get_messages(sid)

        return {"intent": intent, "agent": active_agent,
                "request_id": request_id, "history": history}, sid

    if active_agent and _is_confirmation(user_message):
        intent     = active_agent.value
        request_id = str(uuid.uuid4())

    elif active_agent and _is_mixed_intent(user_message, active_agent):
        intent     = active_agent.value
        request_id = str(uuid.uuid4())
        print(f"[ORCHESTRATOR] Mixed-intent detected — keeping sticky agent: {active_agent.value}")

    else:
        initial_state: OrchestratorState = {
            "user_message":         user_message,
            "conversation_history": history,
            "detected_intent":      "",
            "target_agent":         active_agent or AgentType.BILLING,
            "a2a_response":         "",
            "request_id":           "",
            "final_response":       "",
        }
        intent_state = detect_intent_node(initial_state)
        intent       = intent_state["detected_intent"]
        request_id   = intent_state["request_id"]

        if intent in VALID_INTENTS:
            new_agent = AGENT_TYPE_MAP[intent]
            if new_agent != active_agent:
                session_store.set_active_agent(sid, new_agent)
                active_agent = new_agent
        else:
            if not active_agent:
                return {
                    "intent":     intent,
                    "agent":      None,
                    "request_id": request_id,
                    "response": (
                        "I'm sorry, I couldn't understand your request. "
                        "Please ask about billing, a complaint, or our products."
                    ),
                }, sid

    session_store.append_messages(sid, [{"type": "human", "content": user_message}])
    history = session_store.get_messages(sid)

    return {
        "intent":     intent,
        "agent":      active_agent,
        "request_id": request_id,
        "history":    history,
    }, sid


async def stream_from_orchestrator(user_message: str,session_id:   Optional[str],) -> AsyncIterator[str]:
    info, sid = await _run_chat(user_message, session_id)

    if "response" in info:
        yield _sse("session", {"session_id": sid})
        yield _sse("error",   {"message": info["response"]})
        return

    intent       = info["intent"]
    active_agent: AgentType = info["agent"]
    request_id   = info["request_id"]
    history      = info["history"]

    yield _sse("session", {"session_id": sid})
    yield _sse("intent",  {
        "intent":     intent,
        "agent":      active_agent.value,
        "request_id": request_id,
    })

    req = A2ARequest(
        request_id=request_id,
        source_agent=AgentType.INTENT_DETECTOR,
        target_agent=active_agent,
        user_message=user_message,
        context={"detected_intent": intent, "session_id": sid},
        conversation_history=history,
    )

    base_url   = AGENT_URLS[active_agent]
    stream_url = base_url.replace("/process", "/process/stream")

    collected_tokens: list[str] = []

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream( "POST", stream_url,  json=req.model_dump(),  timeout=60.0,  ) as response:
                response.raise_for_status()

                async for raw_line in response.aiter_lines():
                    if raw_line.startswith("data:"):
                        try:
                            payload = json.loads(raw_line[5:].strip())
                            if payload.get("text"):
                                collected_tokens.append(payload["text"])
                        except json.JSONDecodeError:
                            pass

                    if raw_line:
                        yield raw_line + "\n"
                    else:
                        yield "\n"

        ai_text = "".join(collected_tokens)
        if ai_text:
            session_store.append_messages(sid, [{"type": "ai", "content": ai_text}])

    except httpx.ConnectError:
        yield _sse("error", {
            "message": (
                f"The {active_agent.value} agent is currently unavailable. "
                "Please try again later."
            )
        })
    except httpx.TimeoutException:
        yield _sse("error", {
            "message": (
                f"The {active_agent.value} agent took too long to respond. "
                "Please try again."
            )
        })
    except httpx.HTTPStatusError as e:
        yield _sse("error", {
            "message": (
                f"The {active_agent.value} agent returned an error "
                f"(status {e.response.status_code}). Please try again."
            )
        })


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Intent Detector — Orchestrator", version="2.0")
orchestrator: CompiledStateGraph = build_orchestrator_graph()


# ── Internal trace receiver (accepts forwarded events from specialist agents) ─

@app.post("/internal/trace")
async def internal_trace(event: dict) -> dict:
    """
    Receive a trace event forwarded from a specialist agent process and
    store it in the orchestrator's local trace buffer.
    The dashboard SSE stream reads from this buffer.
    """
    trace_emitter.receive(event)
    return {"status": "ok"}


# ── Chat endpoints ────────────────────────────────────────────────────────────

@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """
    Streaming entry point.  Accepts { "message": "...", "session_id": "..." }.
    First SSE event is always:
        event: session
        data: {"session_id": "<uuid>"}
    followed by the normal intent / tool_call / token / done / error events.
    """
    return StreamingResponse(
        stream_from_orchestrator(payload.message, payload.session_id),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/chat")
async def chat(payload: ChatRequest) -> dict:
    """
    Blocking entry point — internally calls /process/stream so all trace
    events (tool_start, tool_end, agent_handoff) fire during execution.
    Accepts { "message": "...", "session_id": "..." }.
    Returns { "session_id", "intent", "agent", "request_id", "response" }.
    """
    info, sid = await _run_chat(payload.message, payload.session_id)

    if "response" in info:
        return {
            "session_id": sid,
            "intent":     info["intent"],
            "agent":      None,
            "request_id": info.get("request_id", ""),
            "response":   info["response"],
        }

    active_agent: AgentType = info["agent"]
    request_id               = info["request_id"]
    history                  = info["history"]

    trace_emitter.emit(sid, "orchestrator_dispatch",
                       intent=info["intent"],
                       target_agent=active_agent.value,
                       request_id=request_id)

    req = A2ARequest(
        request_id=request_id,
        source_agent=AgentType.INTENT_DETECTOR,
        target_agent=active_agent,
        user_message=payload.message,
        context={"detected_intent": info["intent"], "session_id": sid},
        conversation_history=history,
    )

    # Use /process/stream (not /process) so astream_events fires inside the
    # agent — this is what causes tool_start/tool_end trace events to emit.
    base_url   = AGENT_URLS[active_agent]
    stream_url = base_url.replace("/process", "/process/stream")

    collected_tokens: list[str] = []
    final_result                = ""
    hitl_data: dict             = {}

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", stream_url,
                json=req.model_dump(),
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    if not raw_line.startswith("data:"):
                        continue
                    try:
                        payload_data = json.loads(raw_line[5:].strip())
                        if payload_data.get("text"):
                            collected_tokens.append(payload_data["text"])
                        # Capture hitl_request so we can surface it to the caller
                        if payload_data.get("question"):
                            hitl_data = payload_data
                    except json.JSONDecodeError:
                        pass

        # HITL takes priority — agent suspended waiting for confirmation
        if hitl_data:
            final_result = hitl_data.get("question", "Please confirm the action.")
        else:
            final_result = "".join(collected_tokens)

    except httpx.ConnectError:
        final_result = f"The {active_agent.value} agent is currently unavailable. Please try again later."
    except httpx.TimeoutException:
        final_result = f"The {active_agent.value} agent took too long to respond. Please try again."
    except httpx.HTTPStatusError as e:
        final_result = f"The {active_agent.value} agent returned an error (status {e.response.status_code}). Please try again."
    except Exception as e:
        final_result = f"Error contacting agent: {e}"

    # Write AI reply to session
    if final_result:
        session_store.append_messages(sid, [{"type": "ai", "content": final_result}])

    # Detect if billing agent signalled a handoff to complaint.
    # Trigger phrase: "transferring you to our complaint team"
    # When detected, set pending_handoff so the next user turn routes to complaint.
    if (active_agent == AgentType.BILLING and
            final_result and
            "transferring" in final_result.lower() and
            "complaint" in final_result.lower()):
        session_store.set_metadata(sid, "pending_handoff", "complaint")
        trace_emitter.emit(sid, "pending_handoff_set",
                           from_agent="billing",
                           to_agent="complaint",
                           reason="billing agent signalled transfer to complaint team")

    agent_label = {
        AgentType.BILLING:   "Billing Support",
        AgentType.COMPLAINT: "Complaint Support",
        AgentType.SALES:     "Sales Support",
    }.get(active_agent, "Support")

    result = {
        "session_id": sid,
        "intent":     info["intent"],
        "agent":      active_agent.value,
        "request_id": request_id,
        "response":   f"[{agent_label}]\n\n{final_result}",
    }

    # Surface HITL metadata so the client knows it needs to call /process/resume
    if hitl_data:
        result["hitl_pending"]   = True
        result["hitl_options"]   = hitl_data.get("options", ["Yes", "No"])
        result["ticket_preview"] = hitl_data.get("ticket_preview", {})

    return result


# ── Session management endpoints ──────────────────────────────────────────────

@app.post("/session/reset")
def session_reset(body: SessionResetRequest) -> dict:
    ok = session_store.reset(body.session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found.")
    return {"status": "reset", "session_id": body.session_id}


@app.delete("/session/{session_id}")
def session_delete(session_id: str) -> dict:
    ok = session_store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"status": "deleted", "session_id": session_id}


@app.get("/session/{session_id}")
def session_info(session_id: str) -> dict:
    info = session_store.session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return info


# ── Trace endpoint (dashboard) ────────────────────────────────────────────────

@app.get("/chat/trace/{session_id}")
async def chat_trace(session_id: str) -> StreamingResponse:
    """
    Real-time execution trace stream for the dashboard.

    Subscribe to this SSE endpoint alongside /chat/stream to power a live
    dashboard showing which agent is active, which tools are running, and
    internal agent-to-agent handoffs — including during internal calls that
    are invisible on the user-facing stream.

    Each SSE data payload is a JSON object:
        {"type": "agent_start"|"agent_end"|"tool_start"|"tool_end"|
                 "agent_handoff"|"hitl_requested"|"hitl_resumed"|"error",
         "session_id": "...",
         "ts": "<ISO-8601 UTC>",
         ...event-specific fields...}

    The stream stays open until the session is idle for 5 minutes or the
    client disconnects.
    """
    if session_store.get(session_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"Session '{session_id}' not found.")
    return StreamingResponse(
        trace_emitter.stream(session_id, timeout_s=300),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/chat/trace/{session_id}/replay")
def chat_trace_replay(session_id: str) -> dict:
    """
    Return all buffered trace events for a session as a JSON array.
    Useful for replaying a completed session's execution graph in the dashboard.
    """
    if session_store.get(session_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"Session '{session_id}' not found.")
    return {"session_id": session_id, "events": trace_emitter.get_events(session_id)}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":        "ok",
        "agent":         "intent_detector",
        "active_sessions": len(session_store.all_session_ids()),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "intent_detector.main:app",
        host="0.0.0.0",
        port=INTENT_DETECTOR_PORT,
        reload=True,
    )