import json
import sys
import os
import uvicorn

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain.agents import create_agent
from langchain_core.tools import tool as lc_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel
from typing import AsyncIterator
import httpx

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import COMPLAINT_AGENT_PORT, AGENT_HOST, TICKET_SERVICE_PORT
from shared.llm import get_vertex_llm
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.agent_runner import stream_agent_events, resume_agent
from shared.trace_emitter import trace_emitter
from shared.session_store import session_store

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

TICKET_SERVICE_URL = f"http://{AGENT_HOST}:{TICKET_SERVICE_PORT}"


@lc_tool(
    "get_complaint_history",
    description=(
        "Retrieve the past complaint tickets submitted by a customer. "
        "Use this when the user references a previous complaint, asks about "
        "the status of an existing issue, or wants to see their complaint history."
    ),
)
async def get_complaint_history(customer_id: str) -> list[dict]:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get( f"{TICKET_SERVICE_URL}/tickets/customer/{customer_id}", timeout=10.0  )
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
async def get_ticket_status(ticket_id: int) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(  f"{TICKET_SERVICE_URL}/tickets/{ticket_id}", timeout=10.0 )

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
        "Use this at the start of handling any new complaint before creating a ticket. "
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
    "create_ticket",
    description=(
        "Create a support ticket in the ticket service. "
        "The system will pause and ask the customer to confirm before this executes. "
        "Always call categorize_complaint first to get category and priority."
    ),
)
async def create_ticket(title: str,description: str,customer_id: str,category: str,priority: str,) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{TICKET_SERVICE_URL}/tickets",
                json={"title": title, "description": description,
                      "customer_id": customer_id, "category": category,
                      "priority": priority},
                timeout=10.0,
            )

        r.raise_for_status()
        ticket = r.json()

        return {
            "success":   True,
            "ticket_id": ticket["id"],
            "title":     ticket["title"],
            "status":    ticket["status"],
            "category":  ticket.get("category"),
            "priority":  ticket.get("priority"),
        }

    except httpx.ConnectError:
        return {"error": "Ticket service unavailable."}

    except httpx.TimeoutException:
        return {"error": "Ticket service timed out."}

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}"}


_call_billing_agent_tool = make_agent_call_tool(
    target=AgentType.BILLING,
    description=(
        "Call the billing agent to fetch account balance, invoice history, or payment methods. "
        "Use this when the customer disputes a charge related to their complaint."
    ),
)

_call_sales_agent_tool = make_agent_call_tool(
    target=AgentType.SALES,
    description=(
        "Call the sales agent for product upgrade or plan recommendations. "
        "Use this ONLY after the current complaint is fully resolved AND the customer "
        "explicitly asks about upgrading."
    ),
)

OWN_TOOLS = [get_complaint_history, get_ticket_status,categorize_complaint, create_ticket,]

_RESUME = object()


USER_FACING_PROMPT = """You are a compassionate and professional complaint resolution agent for a telecommunications company.

CONVERSATION BEHAVIOUR:
1. Greet the user warmly on the first message. Continue naturally on subsequent turns.
2. Acknowledge the customer's frustration with ONE short empathetic sentence.
3. You need two things before raising a ticket: a complaint description AND a customer ID.
   - If BOTH are already present in the message, DO NOT ask for anything — proceed immediately
     to step 4. The customer has already given you everything you need.
   - If one is missing, ask for it with a single question.
   - Never re-ask for information already provided.
4. When you have both the complaint description and the customer ID, act immediately:
   a. Call categorize_complaint with the complaint description.
   b. In the SAME response, call create_ticket using the category and priority from step (a).
   Do NOT announce what you are doing. Do NOT ask for confirmation first — the system
   will automatically pause and ask the customer to confirm before the ticket is saved.
5. For history lookups or status checks use get_complaint_history or get_ticket_status.
6. Never expose raw JSON — translate everything into friendly language.
7. Close warmly if the customer says goodbye.

COLLABORATION:
- call_billing_agent: use ONLY when the customer disputes a charge related to their complaint.
- call_sales_agent: use ONLY after complaint is fully resolved and customer asks about plans.
- Never make both calls in the same turn."""

INTERNAL_PROMPT = """You are the complaint agent responding to an internal request from another agent.
Return concise, factual data. Do NOT greet. Do NOT trigger ticket creation.
Only use get_complaint_history and get_ticket_status. Return the data directly."""


llm           = get_vertex_llm(temperature=0, role="specialist")
_checkpointer = InMemorySaver()  # production: AsyncPostgresSaver


def _build_agent(req: A2ARequest, session_id: str):
    if req.is_internal:
        return create_agent(
            llm,
            tools=[get_complaint_history, get_ticket_status],
            system_prompt=INTERNAL_PROMPT,
            checkpointer=_checkpointer,
            name="complaint",
        )

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

    return create_agent(
        llm,
        tools=[*OWN_TOOLS, bound_billing, bound_sales],
        system_prompt=USER_FACING_PROMPT,
        checkpointer=_checkpointer,
        interrupt_before=["tools"],
        name="complaint",
    )


def _build_messages(req: A2ARequest) -> list[dict]:
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
    last_is_user = msgs and msgs[-1]["role"] == "user" and msgs[-1]["content"] == req.user_message

    if not last_is_user:
        msgs.append({"role": "user", "content": req.user_message})

    return msgs


def _get_pending_tool_call(agent, session_id: str) -> dict:
    config = {"configurable": {"thread_id": session_id}}

    try:
        state = agent.get_state(config)
        messages = state.values.get("messages", [])
        for msg in reversed(messages):
            tool_calls = getattr(msg, "tool_calls", [])
            for tc in tool_calls:
                if tc.get("name") == "create_ticket":
                    return tc.get("args", {})
    except Exception:
        pass

    return {}


async def stream_complaint_agent(req: A2ARequest) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(
        session_id, "agent_start", agent="complaint",
        is_internal=req.is_internal,
        triggered_by=req.calling_agent or "orchestrator",
    )

    session_store.get_or_create(session_id)
    session_store.set_metadata(session_id, "last_request_id", req.request_id)

    agent    = _build_agent(req, session_id)
    messages = _build_messages(req)
    config   = {"configurable": {"thread_id": session_id}}
    current_input = messages

    while True:
        hitl_triggered = False

        async for chunk in stream_agent_events(
            agent=agent,
            messages=current_input,
            agent_name="complaint",
            session_id=session_id,
            is_internal=req.is_internal,
        ):
            if "hitl_request" in chunk and not hitl_triggered:
                args = _get_pending_tool_call(agent, session_id)

                if args:
                    hitl_triggered = True
                    title    = args.get("title",    "Support Ticket")
                    category = args.get("category", "N/A")
                    priority = args.get("priority", "N/A")

                    ticket_preview = {
                        "title":       title,
                        "description": args.get("description", ""),
                        "customer_id": args.get("customer_id"),
                        "category":    category,
                        "priority":    priority,
                    }

                    # Exact trace sequence the frontend diagram expects:
                    trace_emitter.emit(
                        session_id, "tool_end",
                        agent="complaint",
                        tool="create_ticket",
                    )
                    trace_emitter.emit(
                        session_id, "hitl_requested",
                        agent="complaint",
                        ticket_preview=ticket_preview,
                    )
                    trace_emitter.emit(
                        session_id, "agent_end",
                        agent="complaint",
                        status="hitl_suspended",
                        is_internal=False,
                    )

                    payload = {
                        "question": (
                            f"I'd like to raise a support ticket on your behalf:\n\n"
                            f"  Title:    {title}\n"
                            f"  Category: {category}\n"
                            f"  Priority: {priority}\n\n"
                            f"Shall I go ahead and create it?"
                        ),
                        "ticket_preview": ticket_preview,
                        "options": ["Yes, raise it", "No, skip it"],
                    }
                    yield f"event: hitl_request\ndata: {json.dumps(payload)}\n\n"

                    return
                else:
                    break
            else:
                yield chunk
        else:
            break

        current_input = _RESUME


async def stream_complaint_resume(session_id: str,hitl_response: str,) -> AsyncIterator[str]:
    confirmed = hitl_response.strip().lower() in ( "yes", "y", "confirm", "ok", "sure", "yes, raise it", "approve")

    req_placeholder = A2ARequest(
        request_id=session_id,
        source_agent=AgentType.COMPLAINT,
        target_agent=AgentType.COMPLAINT,
        user_message="",
        is_internal=False,
    )

    agent  = _build_agent(req_placeholder, session_id)
    config = {"configurable": {"thread_id": session_id}}

    trace_emitter.emit(
        session_id, "agent_start",
        agent="complaint",
        is_internal=False,
        triggered_by="hitl_resume",
    )

    if confirmed:
        pass
    else:
        state = agent.get_state(config)
        msgs = list(state.values.get("messages", []))

        if msgs:
            last_msg = msgs[-1]

            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                from langchain_core.messages import AIMessage

                msgs[-1] = AIMessage(
                    content="The customer declined to raise a ticket.",
                    tool_calls=[],
                )

                agent.update_state(config, {"messages": msgs})

    async for chunk in resume_agent(
        agent=agent,
        session_id=session_id,
        agent_name="complaint",
    ):
        yield chunk


class ResumeRequest(BaseModel):
    request_id:    str
    hitl_response: str


app = FastAPI(title="Complaint Agent", version="5.0")


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    return StreamingResponse(
        stream_complaint_agent(req),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process/resume")
async def process_resume(body: ResumeRequest) -> StreamingResponse:
    session_id = None
    for sid in session_store.all_session_ids():
        if session_store.get_metadata(sid, "last_request_id") == body.request_id:
            session_id = sid
            break

    if not session_id:
        async def not_found():
            yield f"event: error\ndata: {json.dumps({'message': 'No suspended session found.'})}\n\n"

        return StreamingResponse(not_found(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    return StreamingResponse(
        stream_complaint_resume(session_id, body.hitl_response),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    session_id = req.context.get("session_id", req.request_id)
    final_text = ""
    hitl_data  = {}

    async for raw in stream_complaint_agent(req):
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

            except json.JSONDecodeError:
                pass

    if hitl_data:
        return A2AResponse(
            request_id=req.request_id,
            source_agent=AgentType.COMPLAINT,
            status="hitl_pending",
            result=hitl_data.get("question", "Please confirm ticket creation."),
            metadata={
                "hitl_pending":    True,
                "ticket_preview":  hitl_data.get("ticket_preview", {}),
                "resume_endpoint": "/process/resume",
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
    uvicorn.run(
        "complaint_agent.main:app",
        host="0.0.0.0",
        port=COMPLAINT_AGENT_PORT,
        reload=True,
    )