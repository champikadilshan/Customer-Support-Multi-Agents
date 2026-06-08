import uuid
import httpx
from fastapi import FastAPI
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from typing import TypedDict, Literal

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import AGENT_URLS, INTENT_DETECTOR_PORT
from shared.llm import get_vertex_llm

VALID_INTENTS = {"billing", "complaint", "sales"}


# ── LangGraph state ──────────────────────────────────────────────────────────
class OrchestratorState(TypedDict):
    user_message: str
    detected_intent: str        # "billing" | "complaint" | "sales" | "unknown"
    target_agent: AgentType
    a2a_response: str
    request_id: str
    final_response: str


# ── LLM setup ────────────────────────────────────────────────────────────────
llm = get_vertex_llm(temperature=0)


# ── Node 1: Detect intent ────────────────────────────────────────────────────
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
        "target_agent": agent_map.get(intent, AgentType.BILLING),
        "request_id": str(uuid.uuid4()),
    }


# ── Node 2: Dispatch to specialist agent via A2A HTTP call ───────────────────
async def dispatch_to_agent_node(state: OrchestratorState) -> OrchestratorState:
    """
    Builds an A2ARequest and POSTs it to the correct specialist agent.
    Waits for A2AResponse and stores the result.
    """
    req = A2ARequest(
        request_id=state["request_id"],
        source_agent=AgentType.INTENT_DETECTOR,
        target_agent=state["target_agent"],
        user_message=state["user_message"],
        context={"detected_intent": state["detected_intent"]},
    )

    async with httpx.AsyncClient() as client:
        url = AGENT_URLS[state["target_agent"]]
        response = await client.post(
            url,
            json=req.model_dump(),
            timeout=30.0,
        )
        response.raise_for_status()
        a2a_resp = A2AResponse(**response.json())

    return {
        **state,
        "a2a_response": a2a_resp.result,
    }


# ── Node 3: Format final response back to the user ───────────────────────────
def format_response_node(state: OrchestratorState) -> OrchestratorState:
    """
    Cleans and structures the final reply to the end user.
    Adds a small prefix showing which agent handled the request.
    """
    agent_label = {
        AgentType.BILLING:   "💳 Billing Support",
        AgentType.COMPLAINT: "📋 Complaint Support",
        AgentType.SALES:     "🛍️  Sales Support",
    }.get(state["target_agent"], "Support")

    final = f"[{agent_label}]\n\n{state['a2a_response']}"

    return {**state, "final_response": final}


# ── Fallback node for unknown intents ─────────────────────────────────────────
def unknown_intent_node(state: OrchestratorState) -> OrchestratorState:
    return {
        **state,
        "final_response": (
            "I'm sorry, I couldn't understand your request. "
            "Please ask about billing, a complaint, or our products."
        ),
    }


# ── Conditional edge: route based on detected intent ─────────────────────────
def route_intent(state: OrchestratorState) -> Literal["dispatch", "unknown_intent"]:
    if state["detected_intent"] in VALID_INTENTS:
        return "dispatch"
    return "unknown_intent"


# ── Build the LangGraph ───────────────────────────────────────────────────────
def build_orchestrator_graph() -> CompiledStateGraph:
    graph = StateGraph(OrchestratorState)

    # Register nodes
    graph.add_node("detect_intent",   detect_intent_node)
    graph.add_node("dispatch",        dispatch_to_agent_node)
    graph.add_node("format_response", format_response_node)
    graph.add_node("unknown_intent",  unknown_intent_node)

    # Entry point
    graph.set_entry_point("detect_intent")

    # Conditional routing after intent detection
    graph.add_conditional_edges(
        "detect_intent",
        route_intent,
        {
            "dispatch":       "dispatch",
            "unknown_intent": "unknown_intent",
        },
    )

    # Happy path
    graph.add_edge("dispatch",        "format_response")
    graph.add_edge("format_response", END)

    # Fallback path
    graph.add_edge("unknown_intent", END)

    return graph.compile()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Intent Detector — Orchestrator", version="1.0")
orchestrator: CompiledStateGraph = build_orchestrator_graph()


@app.post("/chat")
async def chat(payload: dict) -> dict:
    """
    Entry point for all user messages.
    Expects: { "message": "..." }
    Returns: { "intent": "...", "agent": "...", "response": "..." }
    """
    initial_state: OrchestratorState = {
        "user_message":     payload["message"],
        "detected_intent":  "",
        "target_agent":     AgentType.BILLING,   # placeholder, overwritten by detect_intent_node
        "a2a_response":     "",
        "request_id":       "",
        "final_response":   "",
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
    return {"status": "ok", "agent": "intent_detector_agent"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "intent_detector_agent.main:app",
        host="0.0.0.0",
        port=INTENT_DETECTOR_PORT,
        reload=True,
    )