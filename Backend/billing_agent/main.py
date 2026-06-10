"""
billing_agent/main.py

Refactored to use langchain.agents.create_agent.
The custom run_agent_loop is gone — create_agent handles the ReAct cycle.
"""

import json
import sys
import os
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain.agents import create_agent
from langchain_core.tools import tool as lc_tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from typing import AsyncIterator, Optional
from sqlmodel import select

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import BILLING_AGENT_PORT
from shared.llm import get_vertex_llm
from shared.message_utils import dicts_to_messages, messages_to_dicts
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.agent_runner import stream_agent_events
from shared.trace_emitter import trace_emitter
from billing_agent.database import create_db_and_tables, get_session
from billing_agent.models import AccountBalance, Invoice, PaymentMethod

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


# ── Tools ─────────────────────────────────────────────────────────────────────

@lc_tool(
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


@lc_tool(
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
        {"invoice_id": r.invoice_id, "date": r.date,
         "amount": r.amount, "status": r.status}
        for r in rows
    ]


@lc_tool(
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


_call_complaint_agent_tool = make_agent_call_tool(
    target=AgentType.COMPLAINT,
    description=(
        "Call the complaint agent to CHECK the status of an existing ticket "
        "or retrieve a customer's complaint history. "
        "Use this ONLY when the customer asks about a previous complaint or ticket. "
        "Do NOT use this to create or stage new tickets."
    ),
)

OWN_TOOLS = [get_account_balance, get_invoice_history, get_payment_methods]

# ── Prompts ───────────────────────────────────────────────────────────────────

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
Return a concise, factual answer. Do NOT greet. Do NOT add pleasantries.
Just fetch the data and return the facts.
Use account_id 'ACC-001' as default if none is specified in the task."""

# ── LLM ───────────────────────────────────────────────────────────────────────

llm = get_vertex_llm(temperature=0, role="specialist")

# One InMemorySaver shared across all sessions for this process.
# In production replace with AsyncPostgresSaver.
_checkpointer = InMemorySaver()


# ── Agent factory ─────────────────────────────────────────────────────────────

def _build_agent(req: A2ARequest, session_id: str):
    """
    Build a create_agent graph scoped to this request.

    Internal calls get a stripped-down tool set and terse system prompt.
    User-facing calls get the full tool set including the inter-agent call.
    """
    if req.is_internal:
        tools = list(OWN_TOOLS)
        prompt = INTERNAL_PROMPT
    else:
        bound_complaint = bind_inter_agent_args(
            _call_complaint_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.BILLING.value,
            history=req.conversation_history,
        )
        tools = [*OWN_TOOLS, bound_complaint]
        prompt = USER_FACING_PROMPT

    # create_agent replaces llm.bind_tools(...) + the entire run_agent_loop.
    # It compiles a LangGraph StateGraph internally.
    return create_agent(
        llm,
        tools=tools,
        system_prompt=prompt,
        checkpointer=_checkpointer,
        name="billing",
    )


def _build_messages(req: A2ARequest) -> list[dict]:
    """Convert A2ARequest history + current message into role-dict list."""
    msgs = []
    for d in req.conversation_history:
        t = d.get("type", "")
        if t == "human":
            msgs.append({"role": "user",      "content": d.get("content", "")})
        elif t == "ai":
            msgs.append({"role": "assistant", "content": d.get("content", "")})
        elif t == "tool":
            msgs.append({"role": "tool",      "content": d.get("content", ""),
                         "name": d.get("name", ""), "tool_call_id": d.get("tool_call_id", "")})

    # Only append current message if it's not already the last entry
    last_is_user = msgs and msgs[-1]["role"] == "user" and msgs[-1]["content"] == req.user_message
    if not last_is_user:
        msgs.append({"role": "user", "content": req.user_message})

    return msgs


# ── Streaming entry point ─────────────────────────────────────────────────────

async def stream_billing_agent(req: A2ARequest) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)
    trace_emitter.emit(
        session_id, "agent_start", agent="billing",
        is_internal=req.is_internal,
        triggered_by=req.calling_agent or "orchestrator",
    )

    agent    = _build_agent(req, session_id)
    messages = _build_messages(req)

    async for chunk in stream_agent_events(
        agent=agent,
        messages=messages,
        agent_name="billing",
        session_id=session_id,
        is_internal=req.is_internal,
    ):
        yield chunk


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Billing Agent", version="5.0")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    return StreamingResponse(
        stream_billing_agent(req),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    session_id = req.context.get("session_id", req.request_id)
    final_text = ""

    async for raw in stream_billing_agent(req):
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[5:].strip())
                if payload.get("text"):
                    final_text += payload["text"]
            except json.JSONDecodeError:
                pass

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.BILLING,
        status="success",
        result=final_text or "I was unable to retrieve billing information at this time.",
        metadata={"tools_available": [t.name for t in OWN_TOOLS]},
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