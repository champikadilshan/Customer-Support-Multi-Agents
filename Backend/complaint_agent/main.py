"""
complaint_agent/main.py
-----------------------
Complaint agent — updated for multi-turn conversation sessions.

Key changes vs original
------------------------
1. A2ARequest.conversation_history is used to seed the LangGraph state so
   every turn has full context.

2. System prompt updated with natural-conversation behavioural instructions —
   greet once, never re-ask known info, ask one clarifying question at a time,
   do not pre-announce tool calls.

3. A2AResponse.new_messages carries messages produced this turn back to the
   orchestrator for session storage.

4. HITL (human-in-the-loop) checkpoint is fully preserved.
"""

import json
import operator
import httpx
import sys
import os
import uvicorn

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, BaseMessage
from typing import TypedDict, Annotated, AsyncIterator, Optional, Literal
from pydantic import BaseModel

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import COMPLAINT_AGENT_PORT, AGENT_HOST, TICKET_SERVICE_PORT
from shared.llm import get_vertex_llm
from shared.message_utils import dicts_to_messages, messages_to_dicts

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

TICKET_SERVICE_URL = f"http://{AGENT_HOST}:{TICKET_SERVICE_PORT}"


# ── LangGraph state ───────────────────────────────────────────────────────────

class ComplaintState(TypedDict):
    request_id:          str
    user_message:        str
    messages:            Annotated[list[BaseMessage], operator.add]
    final_response:      str
    hitl_pending:        bool
    hitl_response:       str
    pending_ticket_data: Optional[dict]


class ResumeRequest(BaseModel):
    request_id:    str
    hitl_response: str   # "yes" | "no"


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool(
    "get_complaint_history",
    description=(
        "Retrieve the past complaint tickets submitted by a customer. "
        "Use this when the user references a previous complaint, asks about "
        "the status of an existing issue, or wants to see their complaint history."
    ),
)
def get_complaint_history(customer_id: str) -> list[dict]:
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


@tool(
    "get_ticket_status",
    description=(
        "Retrieve the current status and full details of a specific complaint ticket. "
        "Use this when the user provides a ticket ID and wants an update, "
        "or when following up on a specific issue."
    ),
)
def get_ticket_status(ticket_id: int) -> dict:
    try:
        response = httpx.get(
            f"{TICKET_SERVICE_URL}/tickets/{ticket_id}",
            timeout=10.0,
        )
        if response.status_code == 404:
            return {"ticket_id": ticket_id, "status": "Not Found",
                    "error": f"No ticket found with ID {ticket_id}"}
        if response.status_code != 200:
            return {"error": f"Unexpected error from ticket service (status {response.status_code})"}
        return response.json()
    except httpx.ConnectError:
        return {"error": "Ticket service is unavailable. Please try again later."}
    except httpx.TimeoutException:
        return {"error": "Ticket service request timed out. Please try again."}


@tool(
    "categorize_complaint",
    description=(
        "Analyse a complaint description and return the category and recommended priority. "
        "Use this at the start of handling any new complaint to classify the issue before staging a ticket. "
        "Categories: billing_dispute, service_outage, product_defect, refund_request, rude_staff, delivery_issue, other."
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


@tool(
    "stage_ticket_creation",
    description=(
        "Stage a support ticket for creation pending customer confirmation — does NOT submit it yet. "
        "Use this only after categorize_complaint has been called and you have a full complaint description and customer ID. "
        "The ticket is created only after the customer confirms."
    ),
)
def stage_ticket_creation(
    title:       str,
    description: str,
    customer_id: str,
    category:    str,
    priority:    str,
) -> dict:
    return {
        "staged":      True,
        "title":       title,
        "description": description,
        "customer_id": customer_id,
        "category":    category,
        "priority":    priority,
    }


# ── LLM ───────────────────────────────────────────────────────────────────────

TOOLS          = [get_complaint_history, get_ticket_status, categorize_complaint, stage_ticket_creation]
llm            = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a compassionate and professional complaint resolution agent for a telecommunications company.

CONVERSATION BEHAVIOUR — follow these rules exactly:
1. Greet the user warmly on the very first message of a conversation.
   On subsequent turns, continue naturally without re-introducing yourself.
2. When a customer describes a problem, acknowledge their frustration before
   doing anything else — one empathetic sentence is enough.
3. Before raising a ticket, make sure you have:
   - A clear description of the complaint.
   - The customer's ID (ask for their name and account/phone number if missing).
   Ask ONE clarifying question at a time. Never ask for info already given
   earlier in this conversation.
4. When you have enough information to raise a ticket, you MUST:
   a. Call categorize_complaint to determine category and priority.
   b. Immediately call stage_ticket_creation with those details.
   Do NOT describe what you are about to do. Just call the tools. The system
   will handle confirmation with the customer.
5. NEVER say "I will stage a ticket" or "I am preparing a ticket" — call the
   tool directly.
6. For history lookups or status checks, use get_complaint_history or
   get_ticket_status.
7. Never expose raw JSON or tool output to the customer — translate everything
   into clear, friendly language.
8. If the customer says goodbye or thanks you, close the conversation warmly."""


# ── Nodes ─────────────────────────────────────────────────────────────────────

def agent_node(state: ComplaintState) -> ComplaintState:
    messages_with_system = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *state["messages"],
    ]
    response = llm_with_tools.invoke(messages_with_system)
    return {"messages": [response]}


def hitl_checkpoint_node(state: ComplaintState) -> ComplaintState:
    pending = None
    for msg in reversed(state["messages"]):
        if hasattr(msg, "name") and msg.name == "stage_ticket_creation":
            try:
                content = msg.content
                if isinstance(content, str):
                    content = json.loads(content)
                if isinstance(content, dict) and content.get("staged"):
                    pending = content
                    break
            except (json.JSONDecodeError, AttributeError):
                pass

    return {**state, "hitl_pending": True, "pending_ticket_data": pending}


def hitl_resume_node(state: ComplaintState) -> ComplaintState:
    return {**state, "hitl_pending": False}


def create_ticket_node(state: ComplaintState) -> ComplaintState:
    data = state.get("pending_ticket_data") or {}
    try:
        response = httpx.post(
            f"{TICKET_SERVICE_URL}/tickets",
            json={
                "title":       data.get("title",       "Support Ticket"),
                "description": data.get("description", state["user_message"]),
                "customer_id": data.get("customer_id", "CUST-001"),
                "category":    data.get("category"),
                "priority":    data.get("priority"),
            },
            timeout=10.0,
        )
        response.raise_for_status()
        ticket = response.json()
        confirmation_text = (
            f"Ticket #{ticket['id']} has been successfully created. "
            f"Title: {ticket['title']}. "
            f"Category: {ticket.get('category', 'N/A')}. "
            f"Priority: {ticket.get('priority', 'N/A')}. "
            f"Status: {ticket['status']}."
        )
    except httpx.ConnectError:
        confirmation_text = "I tried to create your ticket but the ticket service is currently unavailable. Please try again later."
    except httpx.TimeoutException:
        confirmation_text = "I tried to create your ticket but the request timed out. Please try again."
    except httpx.HTTPStatusError as e:
        confirmation_text = f"I tried to create your ticket but received an error (status {e.response.status_code}). Please try again."

    return {**state, "messages": [HumanMessage(content=confirmation_text)]}


def format_response_node(state: ComplaintState) -> ComplaintState:
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and msg.content:
            final = msg.content
            break
    else:
        final = "I was unable to process your complaint at this time. Please try again."
    return {**state, "final_response": final}


def ticket_declined_node(state: ComplaintState) -> ComplaintState:
    return {
        **state,
        "final_response": (
            "Understood, I won't raise a ticket for now. "
            "If you change your mind or need anything else, feel free to ask."
        ),
    }


# ── Conditional edges ─────────────────────────────────────────────────────────

def after_tools_condition(
    state: ComplaintState,
) -> Literal["hitl_checkpoint", "agent"]:
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "name") and msg.name == "stage_ticket_creation":
            return "hitl_checkpoint"
    return "agent"


def after_hitl_resume_condition(
    state: ComplaintState,
) -> Literal["create_ticket", "ticket_declined"]:
    response = (state.get("hitl_response") or "").strip().lower()
    return "create_ticket" if response in ("yes", "y", "confirm", "ok", "sure") else "ticket_declined"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_complaint_graph(checkpointer: InMemorySaver) -> CompiledStateGraph:
    graph = StateGraph(ComplaintState)

    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(TOOLS))
    graph.add_node("hitl_checkpoint", hitl_checkpoint_node)
    graph.add_node("hitl_resume",     hitl_resume_node)
    graph.add_node("create_ticket",   create_ticket_node)
    graph.add_node("ticket_declined", ticket_declined_node)
    graph.add_node("format_response", format_response_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: "format_response"},
    )
    graph.add_conditional_edges(
        "tools",
        after_tools_condition,
        {"hitl_checkpoint": "hitl_checkpoint", "agent": "agent"},
    )

    graph.add_edge("hitl_checkpoint", "hitl_resume")

    graph.add_conditional_edges(
        "hitl_resume",
        after_hitl_resume_condition,
        {"create_ticket": "create_ticket", "ticket_declined": "ticket_declined"},
    )

    graph.add_edge("create_ticket",   "format_response")
    graph.add_edge("ticket_declined", END)
    graph.add_edge("format_response", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["hitl_resume"],
    )


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


# ── Streaming generator — initial request ─────────────────────────────────────

async def stream_complaint_graph(
    req:   A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": req.request_id}}

    # Seed state from conversation history
    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: ComplaintState = {
        "request_id":          req.request_id,
        "user_message":        req.user_message,
        "messages":            prior_messages,
        "final_response":      "",
        "hitl_pending":        False,
        "hitl_response":       "",
        "pending_ticket_data": None,
    }

    try:
        async for event in graph.astream_events(initial_state, config, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                if tool_name != "stage_ticket_creation":
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

        snapshot = graph.get_state(config)

        if snapshot.next and "hitl_resume" in snapshot.next:
            ticket = snapshot.values.get("pending_ticket_data") or {}
            yield _sse("hitl_request", {
                "request_id": req.request_id,
                "question": (
                    f"I'd like to raise a support ticket on your behalf:\n\n"
                    f"  Title:    {ticket.get('title', 'Support Ticket')}\n"
                    f"  Category: {ticket.get('category', 'N/A')}\n"
                    f"  Priority: {ticket.get('priority', 'N/A')}\n\n"
                    f"Shall I go ahead and create it?"
                ),
                "ticket_preview": {
                    "title":    ticket.get("title"),
                    "category": ticket.get("category"),
                    "priority": ticket.get("priority"),
                },
                "options": ["Yes, raise it", "No, skip it"],
            })
        else:
            yield _sse("done", {
                "request_id": req.request_id,
                "agent":      AgentType.COMPLAINT.value,
                "status":     "success",
            })

    except Exception as exc:
        yield _sse("error", {"message": str(exc)})


# ── Streaming generator — resume after HITL ───────────────────────────────────

async def stream_complaint_resume(
    request_id:    str,
    hitl_response: str,
    graph:         CompiledStateGraph,
) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": request_id}}
    graph.update_state(config, {"hitl_response": hitl_response})

    try:
        async for event in graph.astream_events(None, config, version="v2"):
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

            elif kind == "on_chain_stream" and name in ("format_response", "ticket_declined"):
                chunk = event.get("data", {}).get("chunk")
                if not isinstance(chunk, dict):
                    continue
                text = chunk.get("final_response", "")
                if isinstance(text, str) and text:
                    yield _sse("token", {"text": text})

        yield _sse("done", {
            "request_id": request_id,
            "agent":      AgentType.COMPLAINT.value,
            "status":     "success",
        })

    except Exception as exc:
        yield _sse("error", {"message": str(exc)})


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Complaint Agent", version="2.0")

checkpointer    = InMemorySaver()
complaint_graph = build_complaint_graph(checkpointer)


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    return StreamingResponse(
        stream_complaint_graph(req, complaint_graph),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process/resume")
async def process_resume(body: ResumeRequest) -> StreamingResponse:
    config   = {"configurable": {"thread_id": body.request_id}}
    snapshot = complaint_graph.get_state(config)

    if not snapshot or not snapshot.next:
        async def not_found():
            yield _sse("error", {
                "message": (
                    f"No suspended graph found for request_id '{body.request_id}'. "
                    "It may have already completed or never existed."
                )
            })
        return StreamingResponse(
            not_found(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        stream_complaint_resume(body.request_id, body.hitl_response, complaint_graph),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    config = {"configurable": {"thread_id": req.request_id}}

    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: ComplaintState = {
        "request_id":          req.request_id,
        "user_message":        req.user_message,
        "messages":            prior_messages,
        "final_response":      "",
        "hitl_pending":        False,
        "hitl_response":       "",
        "pending_ticket_data": None,
    }

    result = await complaint_graph.ainvoke(initial_state, config)

    prior_len     = len(prior_messages)
    new_msgs_dict = messages_to_dicts(result["messages"][prior_len:])

    if result.get("hitl_pending"):
        ticket = result.get("pending_ticket_data") or {}
        return A2AResponse(
            request_id=req.request_id,
            source_agent=AgentType.COMPLAINT,
            status="hitl_pending",
            result=(
                f"A ticket is ready to be raised: "
                f"{ticket.get('title')} ({ticket.get('category')}, {ticket.get('priority')}). "
                f"Call POST /process/resume with hitl_response 'yes' or 'no' to continue."
            ),
            metadata={
                "tools_available": [t.name for t in TOOLS],
                "hitl_pending":    True,
                "ticket_preview":  ticket,
            },
            new_messages=new_msgs_dict,
        )

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.COMPLAINT,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in TOOLS]},
        new_messages=new_msgs_dict,
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