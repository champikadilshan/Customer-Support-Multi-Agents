import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, BaseMessage
from typing import TypedDict, Annotated, AsyncIterator
import operator
import httpx

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import COMPLAINT_AGENT_PORT, AGENT_HOST, TICKET_SERVICE_PORT
from shared.llm import get_vertex_llm


# =============================================================================
# TICKET SERVICE URL — built from shared config, same pattern as AGENT_URLS
# =============================================================================

TICKET_SERVICE_URL = f"http://{AGENT_HOST}:{TICKET_SERVICE_PORT}"


# =============================================================================
# TOOLS — decorated with @tool so LLM can discover and call them
# Each tool makes an HTTP call to the ticket_service instead of querying
# the DB directly. categorize_complaint stays as pure keyword matching.
# =============================================================================

@tool
def get_complaint_history(customer_id: str) -> list[dict]:
    """
    Retrieve the past complaint tickets submitted by a customer.
    Use this when the user references a previous complaint, asks about
    the status of an existing issue, or wants to see their complaint history.
    """
    try:
        response = httpx.get(
            f"{TICKET_SERVICE_URL}/tickets/customer/{customer_id}",
            timeout=10.0,
        )

        if response.status_code == 404:
            return [{"error": f"No complaint history found for customer_id '{customer_id}'"}]

        if response.status_code != 200:
            return [{"error": f"Unexpected error from ticket service (status {response.status_code})"}]

        return response.json()

    except httpx.ConnectError:
        return [{"error": "Ticket service is unavailable. Please try again later."}]
    except httpx.TimeoutException:
        return [{"error": "Ticket service request timed out. Please try again."}]


@tool
def get_ticket_status(ticket_id: int) -> dict:
    """
    Retrieve the current status and full details of a specific complaint ticket.
    Use this when the user provides a ticket ID and wants an update,
    or when following up on a specific issue.
    """
    try:
        response = httpx.get(
            f"{TICKET_SERVICE_URL}/tickets/{ticket_id}",
            timeout=10.0,
        )

        if response.status_code == 404:
            return {
                "ticket_id": ticket_id,
                "status":    "Not Found",
                "error":     f"No ticket found with ID {ticket_id}",
            }

        if response.status_code != 200:
            return {"error": f"Unexpected error from ticket service (status {response.status_code})"}

        return response.json()

    except httpx.ConnectError:
        return {"error": "Ticket service is unavailable. Please try again later."}
    except httpx.TimeoutException:
        return {"error": "Ticket service request timed out. Please try again."}


@tool
def categorize_complaint(description: str) -> dict:
    """
    Analyse the complaint description and return the category and
    recommended priority level.
    Use this at the start of handling a new complaint to understand
    what type of issue the customer is facing.
    Categories: billing_dispute, service_outage, product_defect,
                refund_request, rude_staff, delivery_issue, other.
    """
    description_lower = description.lower()

    if any(w in description_lower for w in ["charge", "invoice", "overcharged", "billed"]):
        category, priority = "billing_dispute", "high"
    elif any(w in description_lower for w in ["outage", "down", "not working", "service"]):
        category, priority = "service_outage", "critical"
    elif any(w in description_lower for w in ["refund", "money back", "return"]):
        category, priority = "refund_request", "high"
    elif any(w in description_lower for w in ["delivery", "shipping", "late", "not arrived"]):
        category, priority = "delivery_issue", "medium"
    elif any(w in description_lower for w in ["rude", "staff", "representative", "agent"]):
        category, priority = "rude_staff", "medium"
    elif any(w in description_lower for w in ["broken", "defect", "damaged", "quality"]):
        category, priority = "product_defect", "medium"
    else:
        category, priority = "other", "low"

    return {
        "category": category,
        "priority": priority,
        "recommended_action": {
            "billing_dispute": "Escalate to billing team for review",
            "service_outage":  "Raise with infrastructure team immediately",
            "refund_request":  "Initiate refund workflow",
            "delivery_issue":  "Contact logistics partner",
            "rude_staff":      "Flag to HR and customer relations",
            "product_defect":  "Initiate replacement or return",
            "other":           "Assign to general support queue",
        }[category],
    }


# =============================================================================
# LANGGRAPH STATE
# messages uses operator.add so each node appends rather than overwrites
# =============================================================================

class ComplaintState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# =============================================================================
# LLM — bind all tools
# =============================================================================

TOOLS = [get_complaint_history, get_ticket_status, categorize_complaint]

llm = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# =============================================================================
# NODES
# =============================================================================

def agent_node(state: ComplaintState) -> ComplaintState:
    """
    Core ReAct node.
    LLM decides whether to call a tool or give a final response.
    Typical flow for a new complaint:
      1. Calls categorize_complaint to understand the issue type
      2. Optionally calls get_complaint_history to check past tickets
      3. Produces a final empathetic and actionable response
    """
    system_prompt = (
        "You are a compassionate complaint resolution agent. "
        "Your goal is to understand the customer's issue, acknowledge their frustration, "
        "and provide a clear next step or resolution. "
        "Use the available tools to look up complaint history and categorize issues. "
        "Use customer_id 'CUST-001' as default if not provided by the user. "
        "Always be empathetic, professional, and solution-focused."
    )

    messages_with_system = [
        {"role": "system", "content": system_prompt},
        *state["messages"],
    ]

    response = llm_with_tools.invoke(messages_with_system)
    return {"messages": [response]}


def format_response_node(state: ComplaintState) -> ComplaintState:
    """
    Extracts the final AI answer after the ReAct loop completes.
    Still used by the non-streaming /process endpoint.
    """
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and msg.content:
            final = msg.content
            break
    else:
        final = "I was unable to process your complaint at this time. Please try again."

    return {**state, "final_response": final}


# =============================================================================
# BUILD GRAPH
# =============================================================================

def build_complaint_graph() -> CompiledStateGraph:
    """
    Graph shape:

                START
                  |
              agent_node  <--------------+
                  |                      |
      tools_condition (conditional edge) |
          +-------+-------+             |
       "tools"         END              |
          |              |              |
       tool_node    format_response     |
          |              |              |
          +--------------+--------------+
                         |
                        END
    """
    graph = StateGraph(ComplaintState)

    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(TOOLS))
    graph.add_node("format_response", format_response_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END:     "format_response",
        },
    )

    graph.add_edge("tools",           "agent")
    graph.add_edge("format_response", END)

    return graph.compile()


# =============================================================================
# SSE HELPERS
# =============================================================================

def _sse(event: str, data: dict) -> str:
    """
    Format a single SSE frame.
    The double newline at the end is required by the SSE spec —
    it signals the end of one event to the client.

    Example output:
        event: tool_call
        data: {"tool": "get_complaint_history"}

    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_complaint_graph(
    req: A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    """
    Async generator that runs the complaint LangGraph via astream_events
    and yields SSE-formatted strings.

    Event types emitted:
      - tool_call : fired when the LLM decides to invoke a tool.
                    Particularly meaningful here because two tools make
                    outbound HTTP calls to the ticket service — the user
                    will notice the pause, so surfacing the tool name lets
                    the UI show "Checking your ticket history…" etc.
      - token     : fired for every text chunk the LLM streams.
                    Carries {"text": "<chunk>"}.
      - done      : fired once after the graph finishes.
                    Carries request_id, agent name, and status.
      - error     : fired if an exception is raised mid-stream.
                    Carries {"message": "<error text>"}.

    Tool execution order for a typical new complaint:
      on_tool_start → categorize_complaint   (instant, keyword matching)
      on_tool_start → get_complaint_history  (slow, hits ticket service over HTTP)
      on_chat_model_stream → token … token … token
      done
    """
    initial_state: ComplaintState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            kind = event["event"]

            # ── Tool invocation ──────────────────────────────────────────────
            # Fired once per tool call, before the tool actually executes.
            # For get_complaint_history and get_ticket_status this is especially
            # useful — they block on HTTP so the UI can show a status hint
            # while the ticket service responds.
            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                yield _sse("tool_call", {"tool": tool_name})

            # ── Streaming LLM tokens ─────────────────────────────────────────
            # on_chat_model_stream fires once per token chunk.
            # We only forward chunks that contain actual text — not the
            # tool-call scaffolding frames which have empty or list content.
            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk is None:
                    continue

                # AIMessageChunk.content is a string for plain text tokens
                # and a list of dicts when the model is mid-tool-call.
                # Only forward plain text.
                content = chunk.content
                if isinstance(content, str) and content:
                    yield _sse("token", {"text": content})
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield _sse("token", {"text": text})

        # ── Completion ───────────────────────────────────────────────────────
        yield _sse("done", {
            "request_id": req.request_id,
            "agent":      AgentType.COMPLAINT.value,
            "status":     "success",
        })

    except Exception as exc:
        # Surface the error as an SSE event so the orchestrator can handle
        # it gracefully rather than seeing a broken stream with no explanation.
        yield _sse("error", {"message": str(exc)})


# =============================================================================
# FASTAPI
# =============================================================================

app = FastAPI(title="Complaint Agent", version="1.0")
complaint_graph: CompiledStateGraph = build_complaint_graph()


# -----------------------------------------------------------------------------
# NEW — streaming endpoint
# The orchestrator calls this and reads the SSE stream token by token.
# Response has no response_model because it is a raw stream, not a JSON body.
# -----------------------------------------------------------------------------
@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    """
    Streaming A2A endpoint.
    Runs the complaint ReAct graph and pushes SSE events as they happen:
      - tool_call events when a tool is about to execute
            (especially useful for the HTTP-bound ticket service tools)
      - token     events for each LLM output chunk
      - done      event when the graph finishes
      - error     event on failure

    The caller must read the response as a stream (not buffer it).
    Content-Type is text/event-stream.
    """
    return StreamingResponse(
        stream_complaint_graph(req, complaint_graph),
        media_type="text/event-stream",
        # X-Accel-Buffering: no tells nginx not to buffer chunks.
        headers={"X-Accel-Buffering": "no"},
    )


# -----------------------------------------------------------------------------
# KEPT — original blocking endpoint
# Still available so the orchestrator can fall back to non-streaming mode
# during a migration, or for callers that don't support SSE.
# -----------------------------------------------------------------------------
@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    """
    Original blocking A2A endpoint — unchanged.
    Runs the full graph and returns a single A2AResponse JSON body.
    """
    initial_state: ComplaintState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    result = await complaint_graph.ainvoke(initial_state)

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.COMPLAINT,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in TOOLS]},
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "complaint"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "complaint_agent.main:app",
        host="0.0.0.0",
        port=COMPLAINT_AGENT_PORT,
        reload=True,
    )