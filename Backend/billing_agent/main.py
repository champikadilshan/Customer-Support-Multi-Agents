import json
import operator
import sys, os
import uvicorn
from accelerate.commands.config.default import description

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, BaseMessage
from typing import TypedDict, Annotated, AsyncIterator
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import BILLING_AGENT_PORT
from shared.llm import get_vertex_llm
from billing_agent.database import create_db_and_tables, get_session
from billing_agent.models import AccountBalance, Invoice, PaymentMethod
from sqlmodel import select

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# LANGGRAPH STATE
class BillingState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# TOOLS
@tool('get_account_balance', description=('Fetch the current account balance, payment due date, and payment status for a given account ID. Use this when the user asks about their balance, how much they owe, or when their next payment is due.'))
def get_account_balance(account_id: str) -> dict:
    """
    Fetch the current account balance, payment due date, and payment status
    for a given account ID.
    Use this when the user asks about their balance, how much they owe,
    or when their next payment is due.
    """
    with get_session() as session: row = session.exec( select(AccountBalance).where(AccountBalance.account_id == account_id) ).first()

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
        rows = session.exec(select(Invoice).where(Invoice.account_id == account_id).order_by(Invoice.date.desc()) .limit(5) ).all()

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
        rows = session.exec( select(PaymentMethod).where(PaymentMethod.account_id == account_id)).all()

    if not rows:
        return {"error": f"No payment methods found for account_id '{account_id}'"}

    methods = []

    for row in rows:
        entry = {
            "type":    row.type,
            "last4":   row.last4,
            "default": row.is_default,
        }

        if row.expiry:
            entry["expiry"] = row.expiry
        if row.bank:
            entry["bank"] = row.bank

        methods.append(entry)

    return {
        "account_id":      account_id,
        "payment_methods": methods,
    }


# LLM
TOOLS = [get_account_balance, get_invoice_history, get_payment_methods]

llm = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# NODES
def agent_node(state: BillingState) -> BillingState:
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
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and msg.content:
            final = msg.content
            break
    else:
        final = "I was unable to retrieve billing information at this time."

    return {**state, "final_response": final}


# BUILD GRAPH
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


# SSE HELPER
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_text(content) -> str:
    """
    Safely pull a plain text string out of whatever content shape
    Vertex AI returns. Handles three forms:
      1. Plain string              → return as-is
      2. List of content blocks   → join all "text" typed blocks
      3. Anything else            → return empty string
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


# STREAMING GENERATOR
async def stream_billing_graph(req: A2ARequest,graph: CompiledStateGraph,) -> AsyncIterator[str]:
    """
    Runs the billing LangGraph via astream_events and yields SSE strings.

    Vertex AI does NOT emit on_chat_model_stream events — it returns the
    full LLM response in a single on_chain_stream event once generation
    is complete.

    We filter on_chain_stream to ONLY the format_response node.
    That node's chunk always has the shape:
        {"final_response": "<the AI answer text>"}
    Filtering by node name prevents tool result JSON from the "tools"
    node leaking out as token events.
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
            name = event.get("name", "")

            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                yield _sse("tool_call", {"tool": tool_name})

            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk is None:
                    continue

                text = _extract_text(chunk.content)
                if text:
                    yield _sse("token", {"text": text})

            elif kind == "on_chain_stream" and name == "format_response":
                chunk = event.get("data", {}).get("chunk")
                if not isinstance(chunk, dict):
                    continue

                text = chunk.get("final_response", "")
                if isinstance(text, str) and text:
                    yield _sse("token", {"text": text})

        yield _sse("done", {
            "request_id": req.request_id,
            "agent":      AgentType.BILLING.value,
            "status":     "success",
        })

    except Exception as exc:
        yield _sse("error", {"message": str(exc)})


# FASTAPI
app = FastAPI(title="Billing Agent", version="1.0")
billing_graph: CompiledStateGraph = build_billing_graph()


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    return StreamingResponse(
        stream_billing_graph(req, billing_graph),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
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

    uvicorn.run(
        "billing_agent.main:app",
        host="0.0.0.0",
        port=BILLING_AGENT_PORT,
        reload=True,
    )