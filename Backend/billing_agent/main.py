"""
billing_agent/main.py
---------------------
Billing agent — updated for multi-turn conversation sessions.

Key changes vs original
------------------------
1. A2ARequest now carries conversation_history (list of serialised
   LangChain messages).  The agent initialises its LangGraph state with
   those messages so the LLM has full context for every turn.

2. System prompt updated with behavioural instructions that drive natural
   multi-turn conversation — ask for missing info, never re-ask what was
   already given, proactively offer complaint creation when anomalies found.

3. A2AResponse now returns new_messages (the messages produced in this
   turn) so the orchestrator can write them back to the session store.

4. Both /process (blocking) and /process/stream (SSE) updated accordingly.
"""

import json
import operator
import sys
import os
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
from billing_agent.database import create_db_and_tables, get_session
from billing_agent.models import AccountBalance, Invoice, PaymentMethod
from sqlmodel import select

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


# ── LangGraph state ───────────────────────────────────────────────────────────

class BillingState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool(
    "get_account_balance",
    description=(
        "Fetch the current account balance, payment due date, and payment status "
        "for a given account ID. Use this when the user asks about their balance, "
        "how much they owe, or when their next payment is due."
    ),
)
def get_account_balance(account_id: str) -> dict:  # noqa: D401
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
        {
            "invoice_id": row.invoice_id,
            "date":       row.date,
            "amount":     row.amount,
            "status":     row.status,
        }
        for row in rows
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
        if row.expiry:
            entry["expiry"] = row.expiry
        if row.bank:
            entry["bank"] = row.bank
        methods.append(entry)

    return {"account_id": account_id, "payment_methods": methods}


# ── LLM ───────────────────────────────────────────────────────────────────────

TOOLS          = [get_account_balance, get_invoice_history, get_payment_methods]
llm            = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a helpful and professional billing support agent for a telecommunications company.

CONVERSATION BEHAVIOUR — follow these rules exactly:
1. Greet the user warmly on the first message of a conversation.
   On subsequent turns, continue naturally without re-introducing yourself.
2. Before calling any tool, make sure you have the customer's account ID.
   If you do not have it, politely ask for their name and account number or
   phone number. Do NOT ask for information already given earlier in this
   conversation.
3. Once you have an account ID, use the tools to fetch the relevant data
   before answering any billing question.
4. When you find an anomaly (e.g. an unexpected charge, a balance spike
   compared to previous invoices), explain it clearly in plain language and
   proactively ask: "Would you like me to raise a complaint ticket about this?"
5. Never repeat a question you have already asked in this conversation.
6. Never expose raw tool output or JSON to the user — always translate it
   into friendly, conversational language.
7. Keep responses concise and focused on what the customer actually asked.
8. If the customer says goodbye or thanks you, close the conversation warmly."""


# ── Nodes ─────────────────────────────────────────────────────────────────────

def agent_node(state: BillingState) -> BillingState:
    messages_with_system = [
        {"role": "system", "content": SYSTEM_PROMPT},
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
    graph = StateGraph(BillingState)

    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(TOOLS))
    graph.add_node("format_response", format_response_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: "format_response"},
    )

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
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


# ── Streaming generator ───────────────────────────────────────────────────────

async def stream_billing_graph(
    req:   A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    """
    Initialise state from conversation history + new user message,
    run the graph, stream SSE events.
    """
    # Reconstruct prior messages from serialised history
    prior_messages = dicts_to_messages(req.conversation_history)

    # The last item in prior_messages is the HumanMessage we appended in the
    # orchestrator; we do NOT add another HumanMessage for the same text.
    # However, if history is empty we add it ourselves.
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: BillingState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       prior_messages,
        "final_response": "",
    }

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_tool_start":
                yield _sse("tool_call", {"tool": event.get("name", "unknown_tool")})

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


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Billing Agent", version="2.0")
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
    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: BillingState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       prior_messages,
        "final_response": "",
    }

    result = await billing_graph.ainvoke(initial_state)

    # Collect only the new messages produced in this turn
    # (everything after the prior history length)
    prior_len    = len(prior_messages)
    new_msgs     = result["messages"][prior_len:]
    new_msgs_dict = messages_to_dicts(new_msgs)

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.BILLING,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in TOOLS]},
        new_messages=new_msgs_dict,
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