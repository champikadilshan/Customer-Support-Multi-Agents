"""
complaint_agent/main.py  (v4 — agentic loop, no LangGraph)

HITL without LangGraph checkpointer:
  - When stage_ticket_creation is called, run_agent_loop yields hitl_request
    and suspends (returns from generator).
  - The hitl_request event carries pending_messages (full serialised message list).
  - /process/stream stores pending_messages + ticket_data in session_store metadata.
  - /process/resume reads them back, injects the user's yes/no, re-enters the loop.
"""

import json
import httpx
import sys
import os
import uvicorn

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool as lc_tool
from typing import AsyncIterator, Optional
from pydantic import BaseModel

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import COMPLAINT_AGENT_PORT, AGENT_HOST, TICKET_SERVICE_PORT
from shared.llm import get_vertex_llm
from shared.message_utils import dicts_to_messages, messages_to_dicts
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.agent_loop import run_agent_loop, get_final_text
from shared.trace_emitter import trace_emitter
from shared.session_store import session_store

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

TICKET_SERVICE_URL = f"http://{AGENT_HOST}:{TICKET_SERVICE_PORT}"


# ── Own tools ─────────────────────────────────────────────────────────────────

@lc_tool(
    "get_complaint_history",
    description=(
        "Retrieve the past complaint tickets submitted by a customer. "
        "Use this when the user references a previous complaint, asks about "
        "the status of an existing issue, or wants to see their complaint history."
    ),
)
def get_complaint_history(customer_id: str) -> list[dict]:
    try:
        r = httpx.get(f"{TICKET_SERVICE_URL}/tickets/customer/{customer_id}", timeout=10.0)
        if r.status_code == 404:
            return [{"error": f"No complaint history found for customer_id '{customer_id}'"}]
        if r.status_code != 200:
            return [{"error": f"Unexpected error (status {r.status_code})"}]
        return r.json()
    except httpx.ConnectError:
        return [{"error": "Ticket service unavailable."}]
    except httpx.TimeoutException:
        return [{"error": "Ticket service timed out."}]


@lc_tool(
    "get_ticket_status",
    description=(
        "Retrieve the current status and full details of a specific complaint ticket. "
        "Use this when the user provides a ticket ID and wants an update."
    ),
)
def get_ticket_status(ticket_id: int) -> dict:
    try:
        r = httpx.get(f"{TICKET_SERVICE_URL}/tickets/{ticket_id}", timeout=10.0)
        if r.status_code == 404:
            return {"ticket_id": ticket_id, "status": "Not Found",
                    "error": f"No ticket found with ID {ticket_id}"}
        if r.status_code != 200:
            return {"error": f"Unexpected error (status {r.status_code})"}
        return r.json()
    except httpx.ConnectError:
        return {"error": "Ticket service unavailable."}
    except httpx.TimeoutException:
        return {"error": "Ticket service timed out."}


@lc_tool(
    "categorize_complaint",
    description=(
        "Analyse a complaint description and return the category and recommended priority. "
        "Use this at the start of handling any new complaint before staging a ticket. "
        "Categories: billing_dispute, service_outage, product_defect, "
        "refund_request, rude_staff, delivery_issue, other."
    ),
)
def categorize_complaint(description: str) -> dict:
    desc = description.lower()
    if any(w in desc for w in ["charge", "invoice", "overcharged", "billed"]):
        category, priority = "billing_dispute", "high"
    elif any(w in desc for w in ["outage", "down", "not working", "service"]):
        category, priority = "service_outage", "critical"
    elif any(w in desc for w in ["refund", "money back", "return"]):
        category, priority = "refund_request", "high"
    elif any(w in desc for w in ["delivery", "shipping", "late", "not arrived"]):
        category, priority = "delivery_issue", "medium"
    elif any(w in desc for w in ["rude", "staff", "representative", "agent"]):
        category, priority = "rude_staff", "medium"
    elif any(w in desc for w in ["broken", "defect", "damaged", "quality"]):
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


@lc_tool(
    "stage_ticket_creation",
    description=(
        "Stage a support ticket for creation pending customer confirmation. "
        "Does NOT create the ticket yet — only after the customer confirms. "
        "Always call categorize_complaint first to get category and priority."
    ),
)
def stage_ticket_creation(
    title: str, description: str, customer_id: str, category: str, priority: str,
) -> dict:
    return {
        "staged": True, "title": title, "description": description,
        "customer_id": customer_id, "category": category, "priority": priority,
    }


@lc_tool(
    "create_ticket",
    description=(
        "Create a support ticket in the ticket service. "
        "Call this ONLY after the customer has confirmed they want the ticket raised. "
        "Use the exact details from the staged ticket."
    ),
)
def create_ticket(
    title: str, description: str, customer_id: str,
    category: str, priority: str,
) -> dict:
    try:
        r = httpx.post(
            f"{TICKET_SERVICE_URL}/tickets",
            json={"title": title, "description": description,
                  "customer_id": customer_id, "category": category,
                  "priority": priority},
            timeout=10.0,
        )
        r.raise_for_status()
        ticket = r.json()
        return {
            "success":     True,
            "ticket_id":   ticket["id"],
            "title":       ticket["title"],
            "status":      ticket["status"],
            "category":    ticket.get("category"),
            "priority":    ticket.get("priority"),
        }
    except httpx.ConnectError:
        return {"error": "Ticket service unavailable."}
    except httpx.TimeoutException:
        return {"error": "Ticket service timed out."}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}"}


# ── Inter-agent tools ─────────────────────────────────────────────────────────

_call_billing_agent_tool = make_agent_call_tool(
    target=AgentType.BILLING,
    description=(
        "Call the billing agent to fetch account balance, invoice history, or payment methods. "
        "Use this when the customer disputes a charge related to their complaint. "
        "Pass a clear task description including the account_id if known."
    ),
)

_call_sales_agent_tool = make_agent_call_tool(
    target=AgentType.SALES,
    description=(
        "Call the sales agent for product upgrade or plan recommendations. "
        "Use this ONLY after the current complaint is fully resolved AND the customer "
        "explicitly asks about upgrading. Do NOT call during active complaint handling."
    ),
)

OWN_TOOLS = [
    get_complaint_history, get_ticket_status,
    categorize_complaint, stage_ticket_creation, create_ticket,
]

# ── LLM ───────────────────────────────────────────────────────────────────────

llm = get_vertex_llm(temperature=0)

# ── System prompts ────────────────────────────────────────────────────────────

USER_FACING_PROMPT = """You are a compassionate and professional complaint resolution agent for a telecommunications company.

CONVERSATION BEHAVIOUR:
1. Greet the user warmly on the first message. Continue naturally on subsequent turns.
2. Acknowledge the customer's frustration with one empathetic sentence before taking action.
3. Before raising a ticket ensure you have a clear complaint description and the customer's ID.
   Ask ONE clarifying question at a time. Never re-ask for information already given.
4. When ready to raise a ticket:
   a. Call categorize_complaint to get category and priority.
   b. Call stage_ticket_creation with those details.
   Do NOT announce what you are about to do — just call the tools.
   The system will pause and ask the customer to confirm before creating the ticket.
5. After the customer confirms (you will receive their yes/no in the conversation),
   if they said yes: call create_ticket with the staged details.
   if they said no: acknowledge and close gracefully.
6. For history lookups or status checks use get_complaint_history or get_ticket_status.
7. Never expose raw JSON — translate everything into friendly language.
8. Close warmly if the customer says goodbye.

COLLABORATION:
- call_billing_agent: use ONLY when the customer disputes a charge related to their
  complaint and you need billing data to support resolution.
- call_sales_agent: use ONLY after complaint is fully resolved and customer asks about plans.
- Never make both calls in the same turn."""

INTERNAL_PROMPT = """You are the complaint agent responding to an internal request from another agent.
Return concise, factual data. Do NOT greet. Do NOT trigger ticket staging.
Only use get_complaint_history and get_ticket_status. Return the data directly."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_messages(req: A2ARequest) -> list:
    system_prompt = INTERNAL_PROMPT if req.is_internal else USER_FACING_PROMPT
    prior         = dicts_to_messages(req.conversation_history)
    if not prior or not isinstance(prior[-1], HumanMessage):
        prior.append(HumanMessage(content=req.user_message))
    return [SystemMessage(content=system_prompt), *prior]


def _build_tool_map(req: A2ARequest, session_id: str) -> dict:
    if req.is_internal:
        tools = [get_complaint_history, get_ticket_status]
    else:
        bound_billing = bind_inter_agent_args(
            _call_billing_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.COMPLAINT.value,
            history=req.conversation_history,
        )
        bound_sales = bind_inter_agent_args(
            _call_sales_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.COMPLAINT.value,
            history=req.conversation_history,
        )
        tools = [*OWN_TOOLS, bound_billing, bound_sales]
    return {t.name: t for t in tools}


# ── Resume request schema ─────────────────────────────────────────────────────

class ResumeRequest(BaseModel):
    request_id:    str
    hitl_response: str   # "yes" | "no"


# ── Streaming generator — initial request ─────────────────────────────────────

async def stream_complaint_agent(req: A2ARequest) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="complaint",
                       is_internal=req.is_internal,
                       triggered_by=req.calling_agent or "orchestrator")

    messages = _build_messages(req)
    tool_map = _build_tool_map(req, session_id)
    llm_with_tools = llm.bind_tools(list(tool_map.values()))

    pending_hitl = False

    async for chunk in run_agent_loop(
        llm_with_tools=llm_with_tools,
        messages=messages,
        tool_map=tool_map,
        agent_name="complaint",
        session_id=session_id,
        is_internal=req.is_internal,
    ):
        # Intercept hitl_request event yielded by run_agent_loop
        lines = chunk.splitlines()
        is_hitl_chunk = any(
            l.strip().startswith("event:") and "hitl_request" in l
            for l in lines
        )

        if is_hitl_chunk:
            for line in lines:
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                    if payload.get("ticket_preview") or payload.get("pending_messages") is not None:
                        session_store.get_or_create(session_id)
                        session_store.set_metadata(session_id, "hitl_pending_request_id",
                                                   req.request_id)
                        session_store.set_metadata(session_id, "hitl_pending_messages",
                                                   payload.get("pending_messages", []))
                        session_store.set_metadata(session_id, "hitl_ticket_data",
                                                   payload.get("ticket_preview", {}))
                        trace_emitter.emit(session_id, "hitl_requested",
                                           agent="complaint",
                                           ticket_preview=payload.get("ticket_preview", {}))
                        # Forward to client without pending_messages
                        client_payload = {k: v for k, v in payload.items()
                                          if k != "pending_messages"}
                        yield f"event: hitl_request\ndata: {json.dumps(client_payload)}\n\n"
                        return
                except (json.JSONDecodeError, KeyError):
                    pass
        else:
            yield chunk


# ── Streaming generator — resume after HITL ───────────────────────────────────

async def stream_complaint_resume(
    request_id: str, hitl_response: str, session_id: str
) -> AsyncIterator[str]:
    """
    Resume a suspended complaint loop after the user has confirmed or declined.

    1. Load pending messages from session metadata.
    2. Inject an assistant acknowledgement + user response into messages.
    3. Re-enter the loop — the LLM sees the confirmation and calls create_ticket
       (if yes) or closes gracefully (if no).
    """
    pending_messages_dicts = session_store.get_metadata(session_id, "hitl_pending_messages")
    ticket_data            = session_store.get_metadata(session_id, "hitl_ticket_data") or {}

    if not pending_messages_dicts:
        yield f"event: error\ndata: {json.dumps({'message': 'No suspended session found.'})}\n\n"
        return

    trace_emitter.emit(session_id, "hitl_resumed",
                       agent="complaint", response=hitl_response)

    # Reconstruct messages from stored state
    messages = dicts_to_messages(pending_messages_dicts)

    # Inject the HITL confirmation as a new human message
    confirmed   = hitl_response.strip().lower() in ("yes", "y", "confirm", "ok", "sure")
    user_text   = (
        f"Yes, please create the ticket: {ticket_data.get('title', 'Support Ticket')}"
        if confirmed
        else "No, please don't raise the ticket."
    )
    messages.append(HumanMessage(content=user_text))

    # Build tool map — same tools as user-facing complaint agent
    # Use stored system prompt via a fresh request-like object
    tool_map = {
        t.name: t for t in [
            get_complaint_history, get_ticket_status,
            categorize_complaint, stage_ticket_creation, create_ticket,
        ]
    }
    llm_with_tools = llm.bind_tools(list(tool_map.values()))

    # Re-enter the loop — LLM will call create_ticket or close gracefully
    async for chunk in run_agent_loop(
        llm_with_tools=llm_with_tools,
        messages=messages,
        tool_map=tool_map,
        agent_name="complaint",
        session_id=session_id,
        is_internal=False,
    ):
        yield chunk

    # Clear HITL metadata
    session_store.set_metadata(session_id, "hitl_pending_messages",  None)
    session_store.set_metadata(session_id, "hitl_ticket_data",       None)
    session_store.set_metadata(session_id, "hitl_pending_request_id", None)

    trace_emitter.emit(session_id, "agent_end", agent="complaint", status="success")


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Complaint Agent", version="4.0")


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    return StreamingResponse(
        stream_complaint_agent(req),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process/resume")
async def process_resume(body: ResumeRequest) -> StreamingResponse:
    # Find session_id from stored pending state
    # We stored request_id → session mapping via session metadata
    # Search all sessions for the matching pending request_id
    session_id = None
    for sid in session_store.all_session_ids():
        stored_rid = session_store.get_metadata(sid, "hitl_pending_request_id")
        if stored_rid == body.request_id:
            session_id = sid
            break

    if not session_id:
        async def not_found():
            yield (f"event: error\ndata: {json.dumps({'message': 'No suspended session found '})}\n\n")
        return StreamingResponse(not_found(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    return StreamingResponse(
        stream_complaint_resume(body.request_id, body.hitl_response, session_id),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="complaint",
                       is_internal=req.is_internal,
                       triggered_by=req.calling_agent or "orchestrator")

    messages       = _build_messages(req)
    tool_map       = _build_tool_map(req, session_id)
    llm_with_tools = llm.bind_tools(list(tool_map.values()))

    final_text  = ""
    hitl_data   = {}

    async for raw in run_agent_loop(
        llm_with_tools=llm_with_tools,
        messages=messages,
        tool_map=tool_map,
        agent_name="complaint",
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
                if payload.get("ticket_preview"):
                    hitl_data = payload
                    session_store.set_metadata(session_id, "hitl_pending_request_id", req.request_id)
                    session_store.set_metadata(session_id, "hitl_pending_messages",
                                               payload.get("pending_messages", []))
                    session_store.set_metadata(session_id, "hitl_ticket_data",
                                               payload.get("ticket_preview", {}))
            except json.JSONDecodeError:
                pass

    if hitl_data:
        ticket = hitl_data.get("ticket_preview", {})
        return A2AResponse(
            request_id=req.request_id,
            source_agent=AgentType.COMPLAINT,
            status="hitl_pending",
            result=hitl_data.get("question", "Please confirm ticket creation."),
            metadata={
                "hitl_pending":    True,
                "ticket_preview":  ticket,
                "resume_endpoint": f"/process/resume",
            },
        )

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.COMPLAINT,
        status="success",
        result=final_text or "I was unable to process your complaint. Please try again.",
        metadata={"tools_available": [t.name for t in OWN_TOOLS]},
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "complaint"}


if __name__ == "__main__":
    uvicorn.run("complaint_agent.main:app", host="0.0.0.0",
                port=COMPLAINT_AGENT_PORT, reload=True)