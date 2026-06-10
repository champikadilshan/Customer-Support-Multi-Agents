import json
import sys
import os
import uvicorn

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from typing import AsyncIterator
from pydantic import BaseModel
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import BILLING_AGENT_PORT
from shared.llm import get_vertex_llm
from shared.message_utils import dicts_to_messages, messages_to_dicts
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.agent_loop import run_agent_loop, get_final_text
from shared.trace_emitter import trace_emitter
from billing_agent.database import create_db_and_tables, get_session
from billing_agent.models import AccountBalance, Invoice, PaymentMethod
from sqlmodel import select

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.tools import tool as lc_tool


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
        rows = session.exec(select(PaymentMethod).where(PaymentMethod.account_id == account_id) ).all()
    if not rows:
        return {"error": f"No payment methods found for account_id '{account_id}'"}

    methods = []

    for row in rows:
        entry = {"type": row.type, "last4": row.last4, "default": row.is_default}
        if row.expiry: entry["expiry"] = row.expiry
        if row.bank:   entry["bank"]   = row.bank
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

llm = get_vertex_llm(temperature=0, role="specialist")


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


def _build_messages(req: A2ARequest) -> list:
    system_prompt = INTERNAL_PROMPT if req.is_internal else USER_FACING_PROMPT
    prior         = dicts_to_messages(req.conversation_history)

    if not prior or not isinstance(prior[-1], HumanMessage):
        prior.append(HumanMessage(content=req.user_message))

    return [SystemMessage(content=system_prompt), *prior]


def _build_tool_map(req: A2ARequest, session_id: str) -> dict:
    if req.is_internal:
        tools = OWN_TOOLS
    else:
        bound_complaint = bind_inter_agent_args(
            _call_complaint_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.BILLING.value,
            history=req.conversation_history,
        )
        tools = [*OWN_TOOLS, bound_complaint]

    return {t.name: t for t in tools if hasattr(t, "name") and t.name}


def _make_llm_with_tools(req: A2ARequest, session_id: str):
    tool_map = _build_tool_map(req, session_id)
    tools    = list(tool_map.values())
    return llm.bind_tools(tools), tool_map


async def stream_billing_agent(req: A2ARequest) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="billing", is_internal=req.is_internal, triggered_by=req.calling_agent or "orchestrator")

    messages              = _build_messages(req)
    llm_with_tools, tool_map = _make_llm_with_tools(req, session_id)

    async for chunk in run_agent_loop(
        llm_with_tools=llm_with_tools,
        messages=messages,
        tool_map=tool_map,
        agent_name="billing",
        session_id=session_id,
        is_internal=req.is_internal,
    ):
        yield chunk


app = FastAPI(title="Billing Agent", version="4.0")


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

    trace_emitter.emit(session_id, "agent_start", agent="billing", is_internal=req.is_internal,triggered_by=req.calling_agent or "orchestrator")

    messages              = _build_messages(req)
    llm_with_tools, tool_map = _make_llm_with_tools(req, session_id)

    final_text = ""

    async for raw in run_agent_loop(
        llm_with_tools=llm_with_tools,
        messages=messages,
        tool_map=tool_map,
        agent_name="billing",
        session_id=session_id,
        is_internal=req.is_internal,
    ):
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
    uvicorn.run("billing_agent.main:app", host="0.0.0.0",
                port=BILLING_AGENT_PORT, reload=True)