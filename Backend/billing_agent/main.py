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

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import BILLING_AGENT_PORT
from shared.llm import get_vertex_llm
from billing_agent.database import create_db_and_tables, get_session
from billing_agent.models import AccountBalance, Invoice, PaymentMethod
from sqlmodel import select


# =============================================================================
# TOOLS — decorated with @tool so LLM can discover and call them
# Each tool opens its own DB session, queries SQLite, returns a dict/list.
# The docstring is what the LLM reads to decide when to call the tool.
# =============================================================================

@tool
def get_account_balance(account_id: str) -> dict:
    """
    Fetch the current account balance, payment due date, and payment status
    for a given account ID.
    Use this when the user asks about their balance, how much they owe,
    or when their next payment is due.
    """
    with get_session() as session:
        row = session.exec(
            select(AccountBalance).where(AccountBalance.account_id == account_id)
        ).first()

    if not row:
        return {"error": f"No account found for account_id '{account_id}'"}

    return {
        "account_id":     row.account_id,
        "balance_due":    row.balance_due,
        "due_date":       row.due_date,
        "payment_status": row.payment_status,
        "last_payment":   row.last_payment,
    }


@tool
def get_invoice_history(account_id: str) -> list[dict]:
    """
    Retrieve the last 5 invoices for a given account ID.
    Use this when the user asks about past invoices, billing history,
    or wants to see previous charges.
    """
    with get_session() as session:
        rows = session.exec(
            select(Invoice)
            .where(Invoice.account_id == account_id)
            .order_by(Invoice.date.desc())
            .limit(5)
        ).all()

    if not rows:
        return [{"error": f"No invoices found for account_id '{account_id}'"}]

    return [
        {
            "invoice_id": row.invoice_id,
            "date":       row.date,
            "amount":     row.amount,
            "status":     row.status,
        }
        for row in rows
    ]


@tool
def get_payment_methods(account_id: str) -> dict:
    """
    Retrieve the saved payment methods on file for a given account ID.
    Use this when the user asks about their saved cards, bank accounts,
    or wants to know how they can pay.
    """
    with get_session() as session:
        rows = session.exec(
            select(PaymentMethod).where(PaymentMethod.account_id == account_id)
        ).all()

    if not rows:
        return {"error": f"No payment methods found for account_id '{account_id}'"}

    methods = []
    for row in rows:
        entry = {
            "type":    row.type,
            "last4":   row.last4,
            "default": row.is_default,
        }
        if row.expiry:       # cards have expiry
            entry["expiry"] = row.expiry
        if row.bank:         # bank accounts have bank name
            entry["bank"]   = row.bank
        methods.append(entry)

    return {
        "account_id":      account_id,
        "payment_methods": methods,
    }


# =============================================================================
# LANGGRAPH STATE
# messages uses operator.add so each node appends rather than overwrites
# =============================================================================

class BillingState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# =============================================================================
# LLM — bind all tools so LLM knows it can call them
# =============================================================================

TOOLS = [get_account_balance, get_invoice_history, get_payment_methods]

llm = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# =============================================================================
# NODES
# =============================================================================

def agent_node(state: BillingState) -> BillingState:
    """
    Core ReAct node.
    The LLM receives the conversation so far (including any tool results)
    and either:
      (a) calls one of the tools  -> ToolNode will execute it next
      (b) produces a final answer -> graph moves to format_response
    """
    system_prompt = (
        "You are a helpful billing support agent. "
        "Use the available tools to look up account information when needed. "
        "When calling tools, use account_id 'ACC-001' as a default if the user "
        "has not provided one. Always be concise and professional."
    )

    messages_with_system = [
        {"role": "system", "content": system_prompt},
        *state["messages"],
    ]

    response = llm_with_tools.invoke(messages_with_system)
    return {"messages": [response]}


def format_response_node(state: BillingState) -> BillingState:
    """
    Extracts the last AI message (the final answer after all tool calls)
    and stores it as final_response for A2AResponse wrapping.
    Still used by the non-streaming /process endpoint.
    """
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and msg.content:
            final = msg.content
            break
    else:
        final = "I was unable to retrieve billing information at this time."

    return {**state, "final_response": final}


# =============================================================================
# BUILD GRAPH
# =============================================================================

def build_billing_graph() -> CompiledStateGraph:
    graph = StateGraph(BillingState)

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
        event: token
        data: {"text": "Your balance"}

    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_billing_graph(
    req: A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    """
    Async generator that runs the billing LangGraph via astream_events
    and yields SSE-formatted strings.

    Event types emitted:
      - tool_call : fired when the LLM decides to invoke a tool.
                    Carries the tool name so the caller can show
                    a status hint like "Looking up your balance…"
      - token     : fired for every text chunk the LLM streams.
                    Carries {"text": "<chunk>"}.
      - done      : fired once after the graph finishes.
                    Carries request_id, agent name, and status.
      - error     : fired if an exception is raised mid-stream.
                    Carries {"message": "<error text>"}.
    """
    initial_state: BillingState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            kind = event["event"]

            # ── Tool invocation ──────────────────────────────────────────────
            # Fired once per tool call, before the tool actually runs.
            # We surface the tool name so the orchestrator / UI can display
            # a "working…" indicator.
            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                yield _sse("tool_call", {"tool": tool_name})

            # ── Streaming LLM tokens ─────────────────────────────────────────
            # on_chat_model_stream fires once per token chunk.
            # We only forward chunks that contain actual text (not tool-call
            # scaffolding, which has no .content or empty .content).
            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk is None:
                    continue

                # AIMessageChunk.content can be a string or a list of dicts
                # (the list form appears when the model is mid-tool-call).
                # We only want plain text chunks.
                content = chunk.content
                if isinstance(content, str) and content:
                    yield _sse("token", {"text": content})
                elif isinstance(content, list):
                    # Extract text from list-form content blocks
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield _sse("token", {"text": text})

        # ── Completion ───────────────────────────────────────────────────────
        yield _sse("done", {
            "request_id": req.request_id,
            "agent":      AgentType.BILLING.value,
            "status":     "success",
        })

    except Exception as exc:
        # Surface the error as an SSE event so the orchestrator can handle
        # it gracefully rather than seeing a broken stream with no explanation.
        yield _sse("error", {"message": str(exc)})


# =============================================================================
# FASTAPI
# =============================================================================

app = FastAPI(title="Billing Agent", version="1.0")
billing_graph: CompiledStateGraph = build_billing_graph()


@app.on_event("startup")
def on_startup():
    """Create DB tables on first run. Safe to call on every restart."""
    create_db_and_tables()


# -----------------------------------------------------------------------------
# NEW — streaming endpoint
# The orchestrator calls this and reads the SSE stream token by token.
# Response has no response_model because it is a raw stream, not a JSON body.
# -----------------------------------------------------------------------------
@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    """
    Streaming A2A endpoint.
    Runs the billing ReAct graph and pushes SSE events as they happen:
      - tool_call events when a DB lookup starts
      - token     events for each LLM output chunk
      - done      event when the graph finishes
      - error     event on failure

    The caller must read the response as a stream (not buffer it).
    Content-Type is text/event-stream.
    """
    return StreamingResponse(
        stream_billing_graph(req, billing_graph),
        media_type="text/event-stream",
        # Disable buffering proxies / nginx would otherwise apply.
        # X-Accel-Buffering: no tells nginx to pass chunks straight through.
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
    initial_state: BillingState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    result = await billing_graph.ainvoke(initial_state)

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.BILLING,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in TOOLS]},
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "billing"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "billing_agent.main:app",
        host="0.0.0.0",
        port=BILLING_AGENT_PORT,
        reload=True,
    )