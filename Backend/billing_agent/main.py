"""
billing_agent/main.py  (v3 — multi-agent collaboration + trace)
"""

import json
import operator
import sys
import os
import time
import uvicorn

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
from shared.message_utils import dicts_to_messages, messages_to_dicts
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.trace_emitter import trace_emitter
from billing_agent.database import create_db_and_tables, get_session
from billing_agent.models import AccountBalance, Invoice, PaymentMethod
from sqlmodel import select

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


# ── LangGraph state ───────────────────────────────────────────────────────────

class BillingState(TypedDict):
    request_id:     str
    user_message:   str
    session_id:     str
    is_internal:    bool
    calling_agent:  str
    history:        list[dict]
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# ── Own tools ─────────────────────────────────────────────────────────────────

@tool(
    "get_account_balance",
    description=(
        "Fetch the current account balance, payment due date, and payment status "
        "for a given account ID. Use this when the user asks about their balance, "
        "how much they owe, or when their next payment is due."
    ),
)
def get_account_balance(account_id: str) -> dict:
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


@tool(
    "get_invoice_history",
    description=(
        "Retrieve the last 5 invoices for a given account ID. "
        "Use this when the user asks about past invoices, billing history, "
        "or wants to see previous charges."
    ),
)
def get_invoice_history(account_id: str) -> list[dict]:
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
        {"invoice_id": r.invoice_id, "date": r.date, "amount": r.amount, "status": r.status}
        for r in rows
    ]


@tool(
    "get_payment_methods",
    description=(
        "Retrieve the saved payment methods on file for a given account ID. "
        "Use this when the user asks about their saved cards, bank accounts, "
        "or wants to know how they can pay."
    ),
)
def get_payment_methods(account_id: str) -> dict:
    with get_session() as session:
        rows = session.exec(
            select(PaymentMethod).where(PaymentMethod.account_id == account_id)
        ).all()
    if not rows:
        return {"error": f"No payment methods found for account_id '{account_id}'"}
    methods = []
    for row in rows:
        entry = {"type": row.type, "last4": row.last4, "default": row.is_default}
        if row.expiry: entry["expiry"] = row.expiry
        if row.bank:   entry["bank"]   = row.bank
        methods.append(entry)
    return {"account_id": account_id, "payment_methods": methods}


# ── Inter-agent tool (unbound — args injected per-request in agent_node) ─────

_call_complaint_agent_tool = make_agent_call_tool(
    target=AgentType.COMPLAINT,
    description=(
        "Call the complaint agent to CHECK the status of an existing ticket "
        "or retrieve a customer's complaint history. "
        "Use this ONLY when the customer asks about a previous complaint or ticket. "
        "Do NOT use this to create or stage new tickets — new tickets are handled "
        "by routing the conversation to the complaint team directly."
    ),
)

OWN_TOOLS = [get_account_balance, get_invoice_history, get_payment_methods]

# ── LLM ───────────────────────────────────────────────────────────────────────

llm = get_vertex_llm(temperature=0)

# ── System prompts ────────────────────────────────────────────────────────────

USER_FACING_PROMPT = """You are a helpful and professional billing support agent for a telecommunications company.

CONVERSATION BEHAVIOUR:
1. Greet the user warmly on the first message. On subsequent turns continue naturally.
2. Before calling any tool, ensure you have the customer's account ID.
   If missing, politely ask for their name and account number or phone number.
   Never re-ask for information already given earlier in this conversation.
3. Use tools to fetch data before answering billing questions.
4. When you find an anomaly (unexpected charge, balance spike vs prior invoices),
   explain it clearly and ask: "Would you like me to raise a complaint ticket about this?"
5. When the customer agrees to raise a ticket, say:
   "I've noted your complaint. I'm transferring you to our complaint team now —
   they will confirm the details and raise the ticket for you."
   Then STOP. Do NOT call any tool. Do NOT try to stage or create the ticket.
   The system will automatically route the next message to the complaint team.
6. You can use call_complaint_agent ONLY to look up an existing ticket status or
   complaint history when the customer asks about a previous complaint.
   NEVER use it to create or stage new tickets.
7. Never expose raw tool output or JSON — translate everything into friendly language.
8. Keep responses concise and focused. Close warmly if the customer says goodbye."""

INTERNAL_PROMPT = """You are the billing agent responding to an internal request from another agent.
Return a concise, factual answer suitable for the calling agent to use in its own response.
Do NOT greet. Do NOT add pleasantries. Just fetch the data and return the facts.
Use account_id 'ACC-001' as default if none is specified in the task."""


# ── Nodes ─────────────────────────────────────────────────────────────────────

def agent_node(state: BillingState) -> BillingState:
    is_internal   = state.get("is_internal", False)
    session_id    = state.get("session_id", "")
    calling_agent = state.get("calling_agent", "")
    history       = state.get("history", [])

    system_prompt = INTERNAL_PROMPT if is_internal else USER_FACING_PROMPT

    # For user-facing turns, bind the inter-agent tool with injected context.
    # For internal turns, suppress it to prevent recursive chains.
    if is_internal:
        all_tools = OWN_TOOLS
    else:
        bound_complaint = bind_inter_agent_args(
            _call_complaint_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.BILLING.value,
            history=history,
        )
        all_tools = [*OWN_TOOLS, bound_complaint]

    llm_with_tools = llm.bind_tools(all_tools)

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
        final = "I was unable to retrieve billing information at this time. Please try again."
    return {**state, "final_response": final}


# ── Build graph ───────────────────────────────────────────────────────────────

def build_billing_graph() -> CompiledStateGraph:
    # ToolNode is created with a placeholder; actual tools are bound per-request
    # in agent_node so the loop guard and arg injection work correctly.
    # We pass OWN_TOOLS here so ToolNode knows how to execute them by name.
    all_possible_tools = [*OWN_TOOLS, _call_complaint_agent_tool]

    graph = StateGraph(BillingState)
    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(all_possible_tools))
    graph.add_node("format_response", format_response_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", tools_condition,
                                {"tools": "tools", END: "format_response"})
    graph.add_edge("tools",           "agent")
    graph.add_edge("format_response", END)

    return graph.compile()


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""


# ── Streaming generator ───────────────────────────────────────────────────────

async def stream_billing_graph(
    req:   A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="billing",
                       is_internal=req.is_internal,
                       triggered_by=req.calling_agent or "orchestrator")

    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: BillingState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "session_id":     session_id,
        "is_internal":    req.is_internal,
        "calling_agent":  req.calling_agent or "",
        "history":        req.conversation_history,
        "messages":       prior_messages,
        "final_response": "",
    }

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                trace_emitter.emit(session_id, "tool_start",
                                   agent="billing", tool=tool_name)
                if not req.is_internal:
                    yield _sse("tool_call", {"tool": tool_name})

            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown_tool")
                trace_emitter.emit(session_id, "tool_end",
                                   agent="billing", tool=tool_name)

            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk is None:
                    continue
                text = _extract_text(chunk.content)
                if text and not req.is_internal:
                    yield _sse("token", {"text": text})

            elif kind == "on_chain_stream" and name == "format_response":
                chunk = event.get("data", {}).get("chunk")
                if not isinstance(chunk, dict):
                    continue
                text = chunk.get("final_response", "")
                if isinstance(text, str) and text and not req.is_internal:
                    yield _sse("token", {"text": text})

        trace_emitter.emit(session_id, "agent_end", agent="billing",
                           status="success", is_internal=req.is_internal)

        if not req.is_internal:
            yield _sse("done", {
                "request_id": req.request_id,
                "agent":      AgentType.BILLING.value,
                "status":     "success",
            })

    except Exception as exc:
        trace_emitter.emit(session_id, "error", agent="billing", message=str(exc))
        if not req.is_internal:
            yield _sse("error", {"message": str(exc)})


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Billing Agent", version="3.0")
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
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="billing",
                       is_internal=req.is_internal,
                       triggered_by=req.calling_agent or "orchestrator")

    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: BillingState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "session_id":     session_id,
        "is_internal":    req.is_internal,
        "calling_agent":  req.calling_agent or "",
        "history":        req.conversation_history,
        "messages":       prior_messages,
        "final_response": "",
    }

    result        = await billing_graph.ainvoke(initial_state)
    prior_len     = len(prior_messages)
    new_msgs_dict = messages_to_dicts(result["messages"][prior_len:])

    trace_emitter.emit(session_id, "agent_end", agent="billing",
                       status="success", is_internal=req.is_internal)

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.BILLING,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in OWN_TOOLS]},
        new_messages=new_msgs_dict,
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "billing"}


if __name__ == "__main__":
    uvicorn.run("billing_agent.main:app", host="0.0.0.0",
                port=BILLING_AGENT_PORT, reload=True)