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
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.trace_emitter import trace_emitter

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

TICKET_SERVICE_URL = f"http://{AGENT_HOST}:{TICKET_SERVICE_PORT}"


class ComplaintState(TypedDict):
    request_id:          str
    user_message:        str
    session_id:          str
    is_internal:         bool
    calling_agent:       str
    history:             list[dict]
    messages:            Annotated[list[BaseMessage], operator.add]
    final_response:      str
    hitl_pending:        bool
    hitl_response:       str
    pending_ticket_data: Optional[dict]


class ResumeRequest(BaseModel):
    request_id:    str
    hitl_response: str


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
        response = httpx.get(f"{TICKET_SERVICE_URL}/tickets/customer/{customer_id}", timeout=10.0)
        if response.status_code == 404:
            return [{"error": f"No complaint history found for customer_id '{customer_id}'"}]
        if response.status_code != 200:
            return [{"error": f"Unexpected error (status {response.status_code})"}]

        return response.json()

    except httpx.ConnectError:
        return [{"error": "Ticket service unavailable."}]

    except httpx.TimeoutException:
        return [{"error": "Ticket service timed out."}]


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
        response = httpx.get(f"{TICKET_SERVICE_URL}/tickets/{ticket_id}", timeout=10.0)
        if response.status_code == 404:
            return {"ticket_id": ticket_id, "status": "Not Found",
                    "error": f"No ticket found with ID {ticket_id}"}
        if response.status_code != 200:
            return {"error": f"Unexpected error (status {response.status_code})"}

        return response.json()

    except httpx.ConnectError:
        return {"error": "Ticket service unavailable."}

    except httpx.TimeoutException:
        return {"error": "Ticket service timed out."}


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
def stage_ticket_creation(title: str, description: str, customer_id: str, category: str, priority: str,) -> dict:
    return {
        "staged": True, "title": title, "description": description,
        "customer_id": customer_id, "category": category, "priority": priority,
    }

_call_billing_agent_tool = make_agent_call_tool(
    target=AgentType.BILLING,
    description=(
        "Call the billing agent to fetch account balance, invoice history, or payment methods. "
        "Use this when the customer disputes a charge related to their complaint (e.g. billed during an outage) "
        "or when you need billing data to support the complaint resolution. "
        "Pass a clear task description including the account_id if known."
    ),
)

_call_sales_agent_tool = make_agent_call_tool(
    target=AgentType.SALES,
    description=(
        "Call the sales agent to provide product upgrade or plan recommendations. "
        "Use this when the customer expresses interest in switching or upgrading their plan "
        "after their complaint has been acknowledged. "
        "Pass context about what the customer is looking for."
    ),
)

OWN_TOOLS = [get_complaint_history, get_ticket_status, categorize_complaint, stage_ticket_creation]

llm = get_vertex_llm(temperature=0)

USER_FACING_PROMPT = """You are a compassionate and professional complaint resolution agent for a telecommunications company.

CONVERSATION BEHAVIOUR:
1. Greet the user warmly on the first message. Continue naturally on subsequent turns.
2. Acknowledge the customer's frustration with one empathetic sentence before taking action.
3. Before raising a ticket ensure you have a clear complaint description and the customer's ID.
   Ask ONE clarifying question at a time. Never re-ask for information already given.
4. When ready to raise a ticket: call categorize_complaint then immediately call stage_ticket_creation.
   Do NOT announce what you are about to do — just call the tools.
5. NEVER say "I will stage a ticket" — call stage_ticket_creation directly.
6. For history lookups or status checks use get_complaint_history or get_ticket_status.
7. Never expose raw JSON — translate everything into friendly language.
8. Close warmly if the customer says goodbye.

COLLABORATION:
- call_billing_agent: use ONLY when the customer explicitly disputes a charge
  directly related to their complaint (e.g. "I was billed during the outage").
  Task format: "Check account ACC-001 balance and advise if a credit applies."
- call_sales_agent: use ONLY after the current complaint is FULLY resolved
  AND the customer explicitly says they want to see upgrade or plan options.
  Do NOT call sales just because the user mentioned plans in passing.
- Only make inter-agent calls when you genuinely need data you cannot provide yourself.
- Never call both billing and sales in the same turn."""

INTERNAL_PROMPT = """You are the complaint agent responding to an internal request from another agent.
Return a concise, factual answer. Do NOT greet. Do NOT trigger ticket staging or HITL.
If asked for ticket status or complaint history, fetch and return the data directly.
Use customer_id 'CUST-001' as default if none is specified."""


def agent_node(state: ComplaintState) -> ComplaintState:
    is_internal   = state.get("is_internal", False)
    session_id    = state.get("session_id", "")
    history       = state.get("history", [])

    system_prompt = INTERNAL_PROMPT if is_internal else USER_FACING_PROMPT

    if is_internal:
        all_tools = [get_complaint_history, get_ticket_status]
    else:
        bound_billing = bind_inter_agent_args(
            _call_billing_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.COMPLAINT.value,
            history=history,
        )
        bound_sales = bind_inter_agent_args(
            _call_sales_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.COMPLAINT.value,
            history=history,
        )
        all_tools = [*OWN_TOOLS, bound_billing, bound_sales]

    llm_with_tools = llm.bind_tools(all_tools)
    messages_with_system = [ {"role": "system", "content": system_prompt}, *state["messages"], ]
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

    if state.get("is_internal", False):
        return {**state, "hitl_pending": False, "pending_ticket_data": pending}

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
        text = (
            f"Ticket #{ticket['id']} has been successfully created. "
            f"Title: {ticket['title']}. Category: {ticket.get('category','N/A')}. "
            f"Priority: {ticket.get('priority','N/A')}. Status: {ticket['status']}."
        )
    except httpx.ConnectError:
        text = "I tried to create your ticket but the ticket service is unavailable. Please try again."
    except httpx.TimeoutException:
        text = "I tried to create your ticket but the request timed out. Please try again."
    except httpx.HTTPStatusError as e:
        text = f"I tried to create your ticket but received an error (status {e.response.status_code})."
    return {**state, "messages": [HumanMessage(content=text)]}


def format_response_node(state: ComplaintState) -> ComplaintState:
    if state.get("is_internal", False) and state.get("pending_ticket_data"):
        ticket = state["pending_ticket_data"]
        final = (
            f"Ticket staged successfully. "
            f"Title: {ticket.get('title', 'Support Ticket')}. "
            f"Category: {ticket.get('category', 'N/A')}. "
            f"Priority: {ticket.get('priority', 'N/A')}. "
            f"Please ask the customer to confirm ticket creation by replying yes or no."
        )

        return {**state, "final_response": final}

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


def after_tools_condition(state: ComplaintState) -> Literal["hitl_checkpoint", "format_response", "agent"]:
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "name") and msg.name == "stage_ticket_creation":
            if state.get("is_internal", False):
                return "format_response"

            return "hitl_checkpoint"

    return "agent"


def after_hitl_resume_condition(state: ComplaintState) -> Literal["create_ticket", "ticket_declined"]:
    response = (state.get("hitl_response") or "").strip().lower()
    return "create_ticket" if response in ("yes", "y", "confirm", "ok", "sure") else "ticket_declined"


def build_complaint_graph(checkpointer: InMemorySaver) -> CompiledStateGraph:
    all_possible_tools = [*OWN_TOOLS, _call_billing_agent_tool, _call_sales_agent_tool]

    graph = StateGraph(ComplaintState)
    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(all_possible_tools))
    graph.add_node("hitl_checkpoint", hitl_checkpoint_node)
    graph.add_node("hitl_resume",     hitl_resume_node)
    graph.add_node("create_ticket",   create_ticket_node)
    graph.add_node("ticket_declined", ticket_declined_node)
    graph.add_node("format_response", format_response_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges("agent", tools_condition,
                                {"tools": "tools", END: "format_response"})
    graph.add_conditional_edges("tools", after_tools_condition,
                                {"hitl_checkpoint": "hitl_checkpoint",
                                 "format_response": "format_response",
                                 "agent":           "agent"})
    graph.add_edge("hitl_checkpoint", "hitl_resume")
    graph.add_conditional_edges("hitl_resume", after_hitl_resume_condition,
                                {"create_ticket": "create_ticket", "ticket_declined": "ticket_declined"})
    graph.add_edge("create_ticket",   "format_response")
    graph.add_edge("ticket_declined", END)
    graph.add_edge("format_response", END)

    return graph.compile(checkpointer=checkpointer, interrupt_before=["hitl_resume"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""


async def stream_complaint_graph( req: A2ARequest, graph: CompiledStateGraph,) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)
    config     = {"configurable": {"thread_id": req.request_id}}

    trace_emitter.emit(session_id, "agent_start", agent="complaint",
                       is_internal=req.is_internal,
                       triggered_by=req.calling_agent or "orchestrator")

    prior_messages = dicts_to_messages(req.conversation_history)

    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: ComplaintState = {
        "request_id":          req.request_id,
        "user_message":        req.user_message,
        "session_id":          session_id,
        "is_internal":         req.is_internal,
        "calling_agent":       req.calling_agent or "",
        "history":             req.conversation_history,
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
                trace_emitter.emit(session_id, "tool_start",
                                   agent="complaint", tool=tool_name)
                if not req.is_internal and tool_name != "stage_ticket_creation":
                    yield _sse("tool_call", {"tool": tool_name})

            elif kind == "on_tool_end":
                trace_emitter.emit(session_id, "tool_end",
                                   agent="complaint", tool=event.get("name", ""))

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
                if isinstance(text, str) and text:
                    if req.is_internal or not ( hasattr(chunk, "get") and chunk.get("hitl_pending") ):
                        yield _sse("token", {"text": text})

        snapshot = graph.get_state(config)

        if snapshot.next and "hitl_resume" in snapshot.next:
            ticket = snapshot.values.get("pending_ticket_data") or {}
            trace_emitter.emit(session_id, "hitl_requested", agent="complaint",
                               ticket_preview=ticket)
            yield _sse("hitl_request", {
                "request_id": req.request_id,
                "question": (
                    f"I'd like to raise a support ticket on your behalf:\n\n"
                    f"  Title:    {ticket.get('title', 'Support Ticket')}\n"
                    f"  Category: {ticket.get('category', 'N/A')}\n"
                    f"  Priority: {ticket.get('priority', 'N/A')}\n\n"
                    f"Shall I go ahead and create it?"
                ),
                "ticket_preview": ticket,
                "options": ["Yes, raise it", "No, skip it"],
            })
        else:
            trace_emitter.emit(session_id, "agent_end", agent="complaint",
                               status="success", is_internal=req.is_internal)
            if not req.is_internal:
                yield _sse("done", {
                    "request_id": req.request_id,
                    "agent":      AgentType.COMPLAINT.value,
                    "status":     "success",
                })

    except Exception as exc:
        trace_emitter.emit(session_id, "error", agent="complaint", message=str(exc))
        if not req.is_internal:
            yield _sse("error", {"message": str(exc)})


async def stream_complaint_resume(request_id: str, hitl_response: str, graph: CompiledStateGraph,session_id: str = "",) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": request_id}}
    graph.update_state(config, {"hitl_response": hitl_response})
    trace_emitter.emit(session_id or request_id, "hitl_resumed",  agent="complaint", response=hitl_response)

    try:
        async for event in graph.astream_events(None, config, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                trace_emitter.emit(session_id or request_id, "tool_start",
                                   agent="complaint", tool=tool_name)
                yield _sse("tool_call", {"tool": tool_name})

            elif kind == "on_tool_end":
                trace_emitter.emit(session_id or request_id, "tool_end",
                                   agent="complaint", tool=event.get("name", ""))

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

        trace_emitter.emit(session_id or request_id, "agent_end",
                           agent="complaint", status="success")
        yield _sse("done", {
            "request_id": request_id,
            "agent":      AgentType.COMPLAINT.value,
            "status":     "success",
        })

    except Exception as exc:
        trace_emitter.emit(session_id or request_id, "error",
                           agent="complaint", message=str(exc))
        yield _sse("error", {"message": str(exc)})


app            = FastAPI(title="Complaint Agent", version="3.0")
checkpointer   = InMemorySaver()
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
                    f"No suspended graph found for request_id '{body.request_id}'."
                )
            })

        return StreamingResponse(not_found(), media_type="text/event-stream",headers={"X-Accel-Buffering": "no"})

    sid = (snapshot.values or {}).get("session_id", body.request_id)

    return StreamingResponse(
        stream_complaint_resume(body.request_id, body.hitl_response,  complaint_graph, session_id=sid),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    session_id = req.context.get("session_id", req.request_id)
    config     = {"configurable": {"thread_id": req.request_id}}

    trace_emitter.emit(session_id, "agent_start", agent="complaint", is_internal=req.is_internal, triggered_by=req.calling_agent or "orchestrator")

    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: ComplaintState = {
        "request_id":          req.request_id,
        "user_message":        req.user_message,
        "session_id":          session_id,
        "is_internal":         req.is_internal,
        "calling_agent":       req.calling_agent or "",
        "history":             req.conversation_history,
        "messages":            prior_messages,
        "final_response":      "",
        "hitl_pending":        False,
        "hitl_response":       "",
        "pending_ticket_data": None,
    }

    result        = await complaint_graph.ainvoke(initial_state, config)
    prior_len     = len(prior_messages)
    new_msgs_dict = messages_to_dicts(result["messages"][prior_len:])

    trace_emitter.emit(session_id, "agent_end", agent="complaint",  status="success", is_internal=req.is_internal)

    if result.get("hitl_pending"):
        ticket = result.get("pending_ticket_data") or {}
        return A2AResponse(
            request_id=req.request_id,
            source_agent=AgentType.COMPLAINT,
            status="hitl_pending",
            result=(
                f"A ticket is ready: {ticket.get('title')} "
                f"({ticket.get('category')}, {ticket.get('priority')}). "
                f"Call POST /process/resume with hitl_response 'yes' or 'no'."
            ),
            metadata={"hitl_pending": True, "ticket_preview": ticket},
            new_messages=new_msgs_dict,
        )

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.COMPLAINT,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in OWN_TOOLS]},
        new_messages=new_msgs_dict,
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "complaint"}


if __name__ == "__main__":
    uvicorn.run("complaint_agent.main:app", host="0.0.0.0",
                port=COMPLAINT_AGENT_PORT, reload=True)