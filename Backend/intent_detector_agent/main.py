import uuid
import json
import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from typing import TypedDict, Literal, AsyncIterator

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import AGENT_URLS, INTENT_DETECTOR_PORT
from shared.llm import get_vertex_llm

VALID_INTENTS = {"billing", "complaint", "sales"}


# =============================================================================
# LANGGRAPH STATE
# =============================================================================

class OrchestratorState(TypedDict):
    user_message:    str
    detected_intent: str        # "billing" | "complaint" | "sales" | "unknown"
    target_agent:    AgentType
    a2a_response:    str
    request_id:      str
    final_response:  str


# =============================================================================
# LLM
# =============================================================================

llm = get_vertex_llm(temperature=0)


# =============================================================================
# NODE 1 — Detect intent
# =============================================================================

def detect_intent_node(state: OrchestratorState) -> OrchestratorState:
    """
    Uses LLM to classify the user message into one of:
    billing, complaint, sales.
    Generates a unique request_id for tracing across agents.
    """
    prompt = f"""
    You are an intent classifier for a customer support system.
    Classify the following user message into EXACTLY one of these categories:
    - billing   (invoices, payments, charges, account balance)
    - complaint (issues, problems, bad experience, refund requests)
    - sales     (product info, pricing, promotions, purchasing)

    Reply with ONLY the single word label. Nothing else.

    User message: {state['user_message']}
    """
    intent = llm.invoke(prompt).content.strip().lower()

    # Fallback to unknown if LLM returns unexpected value
    if intent not in VALID_INTENTS:
        intent = "unknown"

    agent_map = {
        "billing":   AgentType.BILLING,
        "complaint": AgentType.COMPLAINT,
        "sales":     AgentType.SALES,
    }

    return {
        **state,
        "detected_intent": intent,
        "target_agent":    agent_map.get(intent, AgentType.BILLING),
        "request_id":      str(uuid.uuid4()),
    }


# =============================================================================
# NODE 2 — Dispatch to specialist agent via A2A HTTP call
# Used only by the original blocking /chat endpoint — unchanged.
# =============================================================================

async def dispatch_to_agent_node(state: OrchestratorState) -> OrchestratorState:
    """
    Builds an A2ARequest and POSTs it to the correct specialist agent.
    Waits for A2AResponse and stores the result.
    Handles downstream failures gracefully so the orchestrator never crashes.
    """
    req = A2ARequest(
        request_id=state["request_id"],
        source_agent=AgentType.INTENT_DETECTOR,
        target_agent=state["target_agent"],
        user_message=state["user_message"],
        context={"detected_intent": state["detected_intent"]},
    )

    try:
        async with httpx.AsyncClient() as client:
            url = AGENT_URLS[state["target_agent"]]
            response = await client.post(
                url,
                json=req.model_dump(),
                timeout=30.0,
            )
            response.raise_for_status()
            a2a_resp = A2AResponse(**response.json())
            return {**state, "a2a_response": a2a_resp.result}

    except httpx.ConnectError:
        agent_name = state["target_agent"].value
        return {
            **state,
            "a2a_response": (
                f"The {agent_name} agent is currently unavailable. "
                f"Please try again later."
            ),
        }

    except httpx.TimeoutException:
        agent_name = state["target_agent"].value
        return {
            **state,
            "a2a_response": (
                f"The {agent_name} agent took too long to respond. "
                f"Please try again."
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


# =============================================================================
# NODE 3 — Format final response back to the user
# =============================================================================

def format_response_node(state: OrchestratorState) -> OrchestratorState:
    """
    Cleans and structures the final reply to the end user.
    Adds a small prefix showing which agent handled the request.
    """
    agent_label = {
        AgentType.BILLING:   "Billing Support",
        AgentType.COMPLAINT: "Complaint Support",
        AgentType.SALES:     "Sales Support",
    }.get(state["target_agent"], "Support")

    final = f"[{agent_label}]\n\n{state['a2a_response']}"

    return {**state, "final_response": final}


# =============================================================================
# FALLBACK NODE — unknown intent
# =============================================================================

def unknown_intent_node(state: OrchestratorState) -> OrchestratorState:
    return {
        **state,
        "final_response": (
            "I'm sorry, I couldn't understand your request. "
            "Please ask about billing, a complaint, or our products."
        ),
    }


# =============================================================================
# CONDITIONAL EDGE — route based on detected intent
# =============================================================================

def route_intent(state: OrchestratorState) -> Literal["dispatch", "unknown_intent"]:
    if state["detected_intent"] in VALID_INTENTS:
        return "dispatch"
    return "unknown_intent"


# =============================================================================
# BUILD GRAPH
# =============================================================================

def build_orchestrator_graph() -> CompiledStateGraph:
    """
    Graph shape:

                        START
                          |
                   detect_intent_node
                          |
              conditional edge (route_intent)
                 +--------+--------+
                 |                 |
            "dispatch"      "unknown_intent"
                 |                 |
       dispatch_to_agent       unknown_intent_node
                 |                 |
        format_response_node      END
                 |
                END
    """
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


# =============================================================================
# SSE HELPER
# =============================================================================

def _sse(event: str, data: dict) -> str:
    """
    Format a single SSE frame.
    The double newline at the end is required by the SSE spec —
    it signals the end of one event to the client.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# =============================================================================
# STREAMING DISPATCH — used only by /chat/stream
# Bypasses the LangGraph dispatch node entirely.
# Calls detect_intent_node directly (blocking, ~1s), then opens an httpx
# SSE stream to the specialist agent and forwards every line as-is.
# =============================================================================

async def stream_from_orchestrator(user_message: str) -> AsyncIterator[str]:
    """
    Full streaming pipeline:

      1. Run detect_intent_node directly (blocking LLM call, fast).
         Yield an `intent` SSE event immediately so the client knows
         which agent is handling the request before any tokens arrive.

      2. Build an A2ARequest and open an httpx SSE stream to the
         specialist agent's /process/stream endpoint.

      3. Forward every line from the specialist stream straight to
         the client — no buffering, no transformation.
         The specialist already emits well-formed SSE lines
         (event: …, data: …, blank line) so we pass them through raw.

      4. Handle all error cases as SSE error events so the client
         always sees a clean stream regardless of what goes wrong.

    Why bypass the graph for streaming dispatch?
      LangGraph's ainvoke is request/response — it collects the full
      result before returning. There is no way to forward a live SSE
      stream from a downstream agent through a LangGraph node.
      The graph is still used for the blocking /chat endpoint unchanged.
    """

    # ── Phase 1: Intent detection ────────────────────────────────────────────
    # Call detect_intent_node directly instead of going through ainvoke.
    # This is the same function the graph calls — no duplication of logic.
    initial_state: OrchestratorState = {
        "user_message":    user_message,
        "detected_intent": "",
        "target_agent":    AgentType.BILLING,   # placeholder, overwritten below
        "a2a_response":    "",
        "request_id":      "",
        "final_response":  "",
    }

    state = detect_intent_node(initial_state)

    intent     = state["detected_intent"]
    target     = state["target_agent"]
    request_id = state["request_id"]

    # Immediately tell the client what we detected — they see this before
    # any tokens arrive from the specialist agent.
    yield _sse("intent", {
        "intent":     intent,
        "agent":      target.value,
        "request_id": request_id,
    })

    # ── Unknown intent early exit ────────────────────────────────────────────
    if intent not in VALID_INTENTS:
        yield _sse("error", {
            "message": (
                "I'm sorry, I couldn't understand your request. "
                "Please ask about billing, a complaint, or our products."
            )
        })
        return

    # ── Phase 2: Build A2ARequest and stream from specialist ─────────────────
    req = A2ARequest(
        request_id=request_id,
        source_agent=AgentType.INTENT_DETECTOR,
        target_agent=target,
        user_message=user_message,
        context={"detected_intent": intent},
    )

    # Derive the streaming URL from AGENT_URLS.
    # AGENT_URLS points to /process — replace with /process/stream.
    base_url    = AGENT_URLS[target]                          # e.g. http://host:8002/process
    stream_url  = base_url.replace("/process", "/process/stream")

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                stream_url,
                json=req.model_dump(),
                timeout=60.0,       # longer than specialist agent's own timeout
            ) as response:
                response.raise_for_status()

                # ── Phase 3: Passthrough ─────────────────────────────────────
                # aiter_lines() yields one line at a time as the specialist
                # pushes them. We forward each line directly — the specialist
                # already formats them as valid SSE (event:, data:, blank).
                # We re-add the newline that aiter_lines() strips.
                async for line in response.aiter_lines():
                    if line:
                        # Non-blank lines: forward with newline restored.
                        # Blank lines (event boundary) are implicit — the next
                        # non-blank line starts a new event frame.
                        yield line + "\n"
                    else:
                        # Blank line = end of SSE event frame.
                        # Must be forwarded so the client's SSE parser fires.
                        yield "\n"

    except httpx.ConnectError:
        yield _sse("error", {
            "message": (
                f"The {target.value} agent is currently unavailable. "
                f"Please try again later."
            )
        })

    except httpx.TimeoutException:
        yield _sse("error", {
            "message": (
                f"The {target.value} agent took too long to respond. "
                f"Please try again."
            )
        })

    except httpx.HTTPStatusError as e:
        yield _sse("error", {
            "message": (
                f"The {target.value} agent returned an error "
                f"(status {e.response.status_code}). Please try again."
            )
        })


# =============================================================================
# FASTAPI
# =============================================================================

app = FastAPI(title="Intent Detector — Orchestrator", version="1.0")
orchestrator: CompiledStateGraph = build_orchestrator_graph()


# -----------------------------------------------------------------------------
# NEW — streaming endpoint
# Runs intent detection then streams the specialist agent's SSE output
# straight through to the client. The client sees one continuous stream
# with events from both the orchestrator (intent) and the specialist
# (tool_call, token, done / error).
# -----------------------------------------------------------------------------
@app.post("/chat/stream")
async def chat_stream(payload: dict) -> StreamingResponse:
    """
    Streaming entry point for all user messages.
    Expects: { "message": "..." }

    Emits a continuous SSE stream:
      event: intent     — which agent was selected (from orchestrator)
      event: tool_call  — a tool is being called  (forwarded from specialist)
      event: token      — one LLM output chunk     (forwarded from specialist)
      event: done       — specialist finished       (forwarded from specialist)
      event: error      — something went wrong      (orchestrator or specialist)
    """
    return StreamingResponse(
        stream_from_orchestrator(payload["message"]),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


# -----------------------------------------------------------------------------
# KEPT — original blocking endpoint, completely unchanged
# -----------------------------------------------------------------------------
@app.post("/chat")
async def chat(payload: dict) -> dict:
    """
    Entry point for all user messages.
    Expects: { "message": "..." }
    Returns: { "intent": "...", "agent": "...", "request_id": "...", "response": "..." }
    """
    initial_state: OrchestratorState = {
        "user_message":    payload["message"],
        "detected_intent": "",
        "target_agent":    AgentType.BILLING,   # placeholder, overwritten by detect_intent_node
        "a2a_response":    "",
        "request_id":      "",
        "final_response":  "",
    }

    result = await orchestrator.ainvoke(initial_state)

    return {
        "intent":     result["detected_intent"],
        "agent":      result["target_agent"],
        "request_id": result["request_id"],
        "response":   result["final_response"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "agent": "intent_detector"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "intent_detector.main:app",
        host="0.0.0.0",
        port=INTENT_DETECTOR_PORT,
        reload=True,
    )