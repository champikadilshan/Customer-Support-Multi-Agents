"""
intent_detector/main.py
-----------------------
Orchestrator with persistent conversation sessions.

Key changes vs original
------------------------
1. Every /chat and /chat/stream request accepts an optional session_id.
   If omitted, a new session is created and the id is returned to the client.

2. Sticky routing (Option B):
   - If the session already has an active_agent, dispatch there directly —
     the full conversation history is still passed so the LLM reasons correctly
     even mid-conversation.
   - If no active_agent yet, run detect_intent_node (which also receives the
     history as context), then set the active_agent for subsequent turns.

3. Topic-change detection:
   - After every intent classification the orchestrator checks whether the new
     intent differs from the sticky agent. If it does, it updates the
     active_agent so the next turn routes to the right specialist.

4. Session management endpoints:
   POST /session/reset   — clear history + active_agent for a session
   DELETE /session/{sid} — remove session entirely
   GET  /session/{sid}   — inspect session (debug)

5. A2ARequest now carries conversation_history (serialised messages).
   A2AResponse now returns new_messages which are written back to the store.
"""

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

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

VALID_INTENTS = {"billing", "complaint", "sales"}

AGENT_TYPE_MAP: dict[str, AgentType] = {
    "billing":   AgentType.BILLING,
    "complaint": AgentType.COMPLAINT,
    "sales":     AgentType.SALES,
}

# ── LangGraph state ───────────────────────────────────────────────────────────

class OrchestratorState(TypedDict):
    user_message:         str
    conversation_history: list[dict]   # serialised prior messages for context
    detected_intent:      str
    target_agent:         AgentType
    a2a_response:         str
    request_id:           str
    final_response:       str

# ── LLM ───────────────────────────────────────────────────────────────────────

llm = get_vertex_llm(temperature=0)

# ── Request / response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None   # client sends this on follow-up turns

class SessionResetRequest(BaseModel):
    session_id: str

# ── Helpers ───────────────────────────────────────────────────────────────────

def _history_text(history: list[dict]) -> str:
    """
    Render serialised history as a readable block for injection into prompts.
    Keeps it concise: only human and AI turns (tool noise excluded).
    """
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


# ── Node 1 — detect / re-detect intent ───────────────────────────────────────

def detect_intent_node(state: OrchestratorState) -> OrchestratorState:
    """
    Uses the LLM to classify the current user message into billing /
    complaint / sales, taking the conversation history into account so
    mid-conversation topic changes are handled correctly.
    """
    history_block = _history_text(state["conversation_history"])
    history_section = (
        f"\n\nConversation so far:\n{history_block}" if history_block else ""
    )

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


# ── Node 2 — dispatch to specialist ──────────────────────────────────────────

async def dispatch_to_agent_node(state: OrchestratorState) -> OrchestratorState:
    """
    Builds an A2ARequest (including full conversation history) and POSTs it
    to the correct specialist agent.  Stores the plain-text result.
    """
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


# ── Node 3 — format final response ───────────────────────────────────────────

def format_response_node(state: OrchestratorState) -> OrchestratorState:
    agent_label = {
        AgentType.BILLING:   "Billing Support",
        AgentType.COMPLAINT: "Complaint Support",
        AgentType.SALES:     "Sales Support",
    }.get(state["target_agent"], "Support")

    final = f"[{agent_label}]\n\n{state['a2a_response']}"
    return {**state, "final_response": final}


# ── Fallback node ─────────────────────────────────────────────────────────────

def unknown_intent_node(state: OrchestratorState) -> OrchestratorState:
    return {
        **state,
        "final_response": (
            "I'm sorry, I couldn't understand your request. "
            "Please ask about billing, a complaint, or our products."
        ),
    }


# ── Conditional edge ──────────────────────────────────────────────────────────

def route_intent(state: OrchestratorState) -> Literal["dispatch", "unknown_intent"]:
    return "dispatch" if state["detected_intent"] in VALID_INTENTS else "unknown_intent"


# ── Build graph ───────────────────────────────────────────────────────────────

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


# ── Core session-aware chat logic ─────────────────────────────────────────────

async def _run_chat(
    user_message: str,
    session_id:   Optional[str],
) -> tuple[dict, str]:
    """
    Shared logic for /chat (blocking) and the intent step of /chat/stream.

    Returns (result_dict, session_id).

    result_dict keys:
        intent, agent, request_id, response, new_messages
    """
    sess = session_store.get_or_create(session_id)
    sid  = sess.session_id

    history     = session_store.get_messages(sid)
    active_agent = session_store.get_active_agent(sid)

    # ── Determine intent / target agent ───────────────────────────────────────
    # Always run intent detection (with history for context), but if a sticky
    # agent is already set we only update it when the intent genuinely changes.
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
        # Update sticky agent whenever intent changes (topic switch)
        if new_agent != active_agent:
            session_store.set_active_agent(sid, new_agent)
            active_agent = new_agent
    else:
        # Unknown intent — keep sticky agent if we have one, else fail gracefully
        if not active_agent:
            return {
                "intent":       intent,
                "agent":        None,
                "request_id":   request_id,
                "response":     (
                    "I'm sorry, I couldn't understand your request. "
                    "Please ask about billing, a complaint, or our products."
                ),
                "new_messages": [],
            }, sid

    # ── Append user message to session ────────────────────────────────────────
    session_store.append_messages(sid, [{"type": "human", "content": user_message}])
    # Refresh history to include the message we just appended
    history = session_store.get_messages(sid)

    return {
        "intent":       intent,
        "agent":        active_agent,
        "request_id":   request_id,
        "history":      history,          # full history including new user msg
    }, sid


# ── Streaming pipeline ────────────────────────────────────────────────────────

async def stream_from_orchestrator(
    user_message: str,
    session_id:   Optional[str],
) -> AsyncIterator[str]:
    """
    Full streaming pipeline with session support.

    1. Resolve session, run intent detection (with history), set sticky agent.
    2. Emit an `intent` SSE event.
    3. Open an httpx SSE stream to the specialist's /process/stream endpoint,
       passing the full conversation history in the A2ARequest body.
    4. Forward every line from the specialist stream to the client.
    5. On `done`, collect the final AI text from the stream and write it back
       to the session as an AI message.
    """
    info, sid = await _run_chat(user_message, session_id)

    # Unknown intent early-exit
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
        context={"detected_intent": intent},
        conversation_history=history,
    )

    base_url   = AGENT_URLS[active_agent]
    stream_url = base_url.replace("/process", "/process/stream")

    # Collect tokens so we can write the AI response back to the session
    collected_tokens: list[str] = []

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", stream_url,
                json=req.model_dump(),
                timeout=60.0,
            ) as response:
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

        # Write the AI reply back to the session store
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
    Blocking entry point.
    Accepts { "message": "...", "session_id": "..." }.
    Returns {
        "session_id": "...",
        "intent": "...",
        "agent": "...",
        "request_id": "...",
        "response": "..."
    }
    """
    info, sid = await _run_chat(payload.message, payload.session_id)

    # Early exit for unknown intent
    if "response" in info:
        return {
            "session_id": sid,
            "intent":     info["intent"],
            "agent":      None,
            "request_id": info["request_id"],
            "response":   info["response"],
        }

    active_agent: AgentType = info["agent"]
    request_id               = info["request_id"]
    history                  = info["history"]

    req = A2ARequest(
        request_id=request_id,
        source_agent=AgentType.INTENT_DETECTOR,
        target_agent=active_agent,
        user_message=payload.message,
        context={"detected_intent": info["intent"]},
        conversation_history=history,
    )

    try:
        async with httpx.AsyncClient() as client:
            url = AGENT_URLS[active_agent]
            response = await client.post(url, json=req.model_dump(), timeout=30.0)
            response.raise_for_status()
            a2a_resp = A2AResponse(**response.json())
    except Exception as e:
        return {
            "session_id": sid,
            "intent":     info["intent"],
            "agent":      active_agent.value,
            "request_id": request_id,
            "response":   f"Error contacting agent: {e}",
        }

    # Write agent reply back to session
    if a2a_resp.new_messages:
        session_store.append_messages(sid, a2a_resp.new_messages)
    elif a2a_resp.result:
        session_store.append_messages(sid, [{"type": "ai", "content": a2a_resp.result}])

    agent_label = {
        AgentType.BILLING:   "Billing Support",
        AgentType.COMPLAINT: "Complaint Support",
        AgentType.SALES:     "Sales Support",
    }.get(active_agent, "Support")

    return {
        "session_id": sid,
        "intent":     info["intent"],
        "agent":      active_agent.value,
        "request_id": request_id,
        "response":   f"[{agent_label}]\n\n{a2a_resp.result}",
    }


# ── Session management endpoints ──────────────────────────────────────────────

@app.post("/session/reset")
def session_reset(body: SessionResetRequest) -> dict:
    """
    Reset a session's conversation history and sticky agent.
    Metadata (resolved account_id etc.) is preserved.
    Returns 404 if the session_id is unknown.
    """
    ok = session_store.reset(body.session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found.")
    return {"status": "reset", "session_id": body.session_id}


@app.delete("/session/{session_id}")
def session_delete(session_id: str) -> dict:
    """Delete a session entirely."""
    ok = session_store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"status": "deleted", "session_id": session_id}


@app.get("/session/{session_id}")
def session_info(session_id: str) -> dict:
    """Inspect a session — useful for debugging."""
    info = session_store.session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return info


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