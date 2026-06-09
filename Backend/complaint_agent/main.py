import json
import operator
import httpx
import sys, os
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

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

TICKET_SERVICE_URL = f"http://{AGENT_HOST}:{TICKET_SERVICE_PORT}"

# LANGGRAPH STATE
class ComplaintState(TypedDict):
    request_id:          str
    user_message:        str
    messages:            Annotated[list[BaseMessage], operator.add]
    final_response:      str
    hitl_pending:        bool
    hitl_response:       str
    pending_ticket_data: Optional[dict]

# Request body for the resume endpoint
class ResumeRequest(BaseModel):
    request_id:    str
    hitl_response: str #y/n


@tool
def get_complaint_history(customer_id: str) -> list[dict]:
    """
    Retrieve the past complaint tickets submitted by a customer.
    Use this when the user references a previous complaint, asks about
    the status of an existing issue, or wants to see their complaint history.
    """
    try:
        response = httpx.get( f"{TICKET_SERVICE_URL}/tickets/customer/{customer_id}", timeout=10.0,  )

        if response.status_code == 404:
            return [{"error": f"No complaint history found for customer_id '{customer_id}'"}]
        if response.status_code != 200:
            return [{"error": f"Unexpected error from ticket service (status {response.status_code})"}]
        return response.json()

    except httpx.ConnectError:
        return [{"error": "Ticket service is unavailable. Please try again later."}]

    except httpx.TimeoutException:
        return [{"error": "Ticket service request timed out. Please try again."}]


@tool
def get_ticket_status(ticket_id: int) -> dict:
    """
    Retrieve the current status and full details of a specific complaint ticket.
    Use this when the user provides a ticket ID and wants an update,
    or when following up on a specific issue.
    """
    try:
        response = httpx.get(f"{TICKET_SERVICE_URL}/tickets/{ticket_id}",timeout=10.0, )

        if response.status_code == 404:
            return {
                "ticket_id": ticket_id,
                "status":    "Not Found",
                "error":     f"No ticket found with ID {ticket_id}",
            }

        if response.status_code != 200:
            return {"error": f"Unexpected error from ticket service (status {response.status_code})"}

        return response.json()

    except httpx.ConnectError:
        return {"error": "Ticket service is unavailable. Please try again later."}

    except httpx.TimeoutException:
        return {"error": "Ticket service request timed out. Please try again."}


@tool
def categorize_complaint(description: str) -> dict:
    """
    Analyse the complaint description and return the category and
    recommended priority level.
    Use this at the start of handling a new complaint to understand
    what type of issue the customer is facing.
    Categories: billing_dispute, service_outage, product_defect,
                refund_request, rude_staff, delivery_issue, other.
    """
    description_lower = description.lower()

    if any(w in description_lower for w in ["charge", "invoice", "overcharged", "billed"]):
        category, priority = "billing_dispute", "high"
    elif any(w in description_lower for w in ["outage", "down", "not working", "service"]):
        category, priority = "service_outage", "critical"
    elif any(w in description_lower for w in ["refund", "money back", "return"]):
        category, priority = "refund_request", "high"
    elif any(w in description_lower for w in ["delivery", "shipping", "late", "not arrived"]):
        category, priority = "delivery_issue", "medium"
    elif any(w in description_lower for w in ["rude", "staff", "representative", "agent"]):
        category, priority = "rude_staff", "medium"
    elif any(w in description_lower for w in ["broken", "defect", "damaged", "quality"]):
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


@tool
def stage_ticket_creation( title: str, description: str, customer_id: str, category: str, priority: str,) -> dict:
    """
    Stage a new support ticket for creation — does NOT create it yet.
    Use this when you have fully understood the customer's complaint and
    want to raise a ticket on their behalf.
    The ticket will only be created after the customer confirms.
    Always call categorize_complaint first so category and priority are accurate.
    """
    return {
        "staged":      True,
        "title":       title,
        "description": description,
        "customer_id": customer_id,
        "category":    category,
        "priority":    priority,
    }


# LLM
TOOLS = [get_complaint_history, get_ticket_status, categorize_complaint, stage_ticket_creation]

llm = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# NODES
def agent_node(state: ComplaintState) -> ComplaintState:
    system_prompt = (
        "You are a compassionate complaint resolution agent. "
        "Your goal is to understand the customer's issue, acknowledge their frustration, "
        "and provide a clear next step or resolution. "
        "Use customer_id 'CUST-001' as default if not provided by the user. "
        "\n\n"
        "STRICT RULES — follow these exactly:\n"
        "1. When a customer describes a new complaint or problem, you MUST:\n"
        "   a. First call categorize_complaint to get the category and priority.\n"
        "   b. Then immediately call stage_ticket_creation with those details.\n"
        "   Do NOT describe what you are going to do. Do NOT ask for confirmation in text. "
        "   Just call the tools. The system will handle confirmation with the user.\n"
        "2. NEVER say 'I will stage a ticket' or 'I am preparing a ticket' — "
        "   just call stage_ticket_creation directly.\n"
        "3. For status checks or history lookups, use get_ticket_status or get_complaint_history.\n"
        "4. Always be empathetic and professional in your final response."
    )

    messages_with_system = [
        {"role": "system", "content": system_prompt},
        *state["messages"],
    ]

    response = llm_with_tools.invoke(messages_with_system)

    return {"messages": [response]}


def hitl_checkpoint_node(state: ComplaintState) -> ComplaintState:
    """
    Extracts the staged ticket data from the last stage_ticket_creation
    tool call result and suspends the graph for human approval.

    This node is listed in interrupt_before at graph compile time — LangGraph
    will pause execution here and wait for graph.update_state() + graph.invoke()
    to be called from the /process/resume endpoint.
    """
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

    return {
        **state,
        "hitl_pending":        True,
        "pending_ticket_data": pending,
    }


def hitl_resume_node(state: ComplaintState) -> ComplaintState:
    """
    Clears the HITL pending flag after the human has responded.
    The actual routing (yes → create_ticket, no → format_response)
    is handled by the conditional edge that follows this node.
    """
    return {
        **state,
        "hitl_pending": False,
    }


def create_ticket_node(state: ComplaintState) -> ComplaintState:
    """
    Called only after the human approved ticket creation.
    POSTs to the ticket service and stores the result in messages
    so format_response_node can reference the ticket ID.
    """
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

    return {
        **state,
        "messages": [HumanMessage(content=confirmation_text)],
    }


def format_response_node(state: ComplaintState) -> ComplaintState:
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and msg.content:
            final = msg.content
            break
    else:
        final = "I was unable to process your complaint at this time. Please try again."

    return {**state, "final_response": final}


def ticket_declined_node(state: ComplaintState) -> ComplaintState:
    """Sets a friendly final response when the user declined ticket creation."""
    return {
        **state,
        "final_response": (
            "Understood, I won't raise a ticket for now. "
            "If you change your mind or need anything else, feel free to ask."
        ),
    }


# CONDITIONAL EDGES
def after_tools_condition(state: ComplaintState) -> Literal["hitl_checkpoint", "agent"]:
    """
    After the ToolNode runs, check if the last tool called was
    stage_ticket_creation. If yes, divert to HITL. Otherwise loop
    back to the agent as normal.
    """
    messages = state.get("messages", [])

    for msg in reversed(messages):
        if hasattr(msg, "name") and msg.name == "stage_ticket_creation":
            return "hitl_checkpoint"

    return "agent"


def after_hitl_resume_condition(state: ComplaintState) -> Literal["create_ticket", "ticket_declined"]:
    """Route based on the human's yes/no response."""
    response = (state.get("hitl_response") or "").strip().lower()

    if response in ("yes", "y", "confirm", "ok", "sure"):
        return "create_ticket"

    return "ticket_declined"


# BUILD GRAPH
def build_complaint_graph(checkpointer: InMemorySaver) -> CompiledStateGraph:
    """
    Graph shape:

        START
          |
        agent ──(tools_condition)──► tools
          ▲                            |
          └──(after_tools_condition)───┤
                  "agent"              |
                                       └──(after_tools_condition)──► hitl_checkpoint
                                                                            |
                                                                     [INTERRUPT HERE]
                                                                            |
                                                                      hitl_resume
                                                                            |
                                              ┌─────────────────────────────┘
                                    "create_ticket"              "ticket_declined"
                                          |                             |
                                   create_ticket_node          ticket_declined_node
                                          |                             |
                                   format_response ◄───────────────────┘
                                          |
                                         END

    agent ──(tools_condition END)──► format_response ──► END
    """
    graph = StateGraph(ComplaintState)

    graph.add_node("agent",            agent_node)
    graph.add_node("tools",            ToolNode(TOOLS))
    graph.add_node("hitl_checkpoint",  hitl_checkpoint_node)
    graph.add_node("hitl_resume",      hitl_resume_node)
    graph.add_node("create_ticket",    create_ticket_node)
    graph.add_node("ticket_declined",  ticket_declined_node)
    graph.add_node("format_response",  format_response_node)

    graph.set_entry_point("agent")

    # agent → tools OR format_response (standard tools_condition)
    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END:     "format_response",
        },
    )

    # tools → hitl_checkpoint (if stage_ticket_creation was called) OR back to agent
    graph.add_conditional_edges(
        "tools",
        after_tools_condition,
        {
            "hitl_checkpoint": "hitl_checkpoint",
            "agent":           "agent",
        },
    )

    # hitl_checkpoint suspends here (interrupt_before in compile())
    graph.add_edge("hitl_checkpoint", "hitl_resume")

    # hitl_resume → create_ticket OR ticket_declined
    graph.add_conditional_edges(
        "hitl_resume",
        after_hitl_resume_condition,
        {
            "create_ticket":   "create_ticket",
            "ticket_declined": "ticket_declined",
        },
    )

    graph.add_edge("create_ticket",   "format_response")
    graph.add_edge("ticket_declined", END)
    graph.add_edge("format_response", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["hitl_resume"],
    )


# SSE HELPERS
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)

    return ""


# STREAMING GENERATOR — initial request
async def stream_complaint_graph( req: A2ARequest, graph: CompiledStateGraph,) -> AsyncIterator[str]:
    """
    Runs the complaint LangGraph via astream_events and yields SSE strings.

    If the graph reaches hitl_checkpoint, execution is automatically
    suspended by LangGraph (interrupt_before=["hitl_resume"]).
    We detect this by checking the graph's current node after streaming ends —
    if it stopped at hitl_resume, we emit a hitl_request SSE event so the
    client knows to show the confirmation UI.
    """
    config = {"configurable": {"thread_id": req.request_id}}

    initial_state: ComplaintState = {
        "request_id":          req.request_id,
        "user_message":        req.user_message,
        "messages":            [HumanMessage(content=req.user_message)],
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
                "question":   (
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


# STREAMING GENERATOR — resume after HITL
async def stream_complaint_resume(request_id:    str, hitl_response: str,graph:         CompiledStateGraph,) -> AsyncIterator[str]:
    """
    Resumes a suspended complaint graph after the human has responded.

    1. Injects hitl_response into the checkpointed state.
    2. Calls graph.astream_events(None, config) — passing None as input
       tells LangGraph to resume from the checkpoint rather than start fresh.
    3. Streams the remainder of the graph (create_ticket or ticket_declined
       → format_response) as normal SSE events.
    """

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

            elif kind == "on_chain_stream" and name == "format_response":
                chunk = event.get("data", {}).get("chunk")
                if not isinstance(chunk, dict):
                    continue

                text = chunk.get("final_response", "")
                if isinstance(text, str) and text:
                    yield _sse("token", {"text": text})

            elif kind == "on_chain_stream" and name == "ticket_declined":
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


# FASTAPI
app = FastAPI(title="Complaint Agent", version="1.0")

# InMemorySaver holds all checkpoints in RAM. (Replace with SqliteSaver or RedisSaver for persistence across restarts.)
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
    """
    Resume a suspended complaint graph after human approval/rejection.

    Expects: { "request_id": "...", "hitl_response": "yes" | "no" }

    Emits the same SSE event types as /process/stream:
      event: tool_call  — if create_ticket_node fires any sub-tools
      event: token      — LLM response chunks
      event: done       — graph completed
      event: error      — something went wrong
    """
    config   = {"configurable": {"thread_id": body.request_id}}
    snapshot = complaint_graph.get_state(config)

    if not snapshot or not snapshot.next:
        async def not_found():
            yield _sse("error", {
                "message": f"No suspended graph found for request_id '{body.request_id}'. "
                           f"It may have already completed or never existed."
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

    initial_state: ComplaintState = {
        "request_id":          req.request_id,
        "user_message":        req.user_message,
        "messages":            [HumanMessage(content=req.user_message)],
        "final_response":      "",
        "hitl_pending":        False,
        "hitl_response":       "",
        "pending_ticket_data": None,
    }

    result = await complaint_graph.ainvoke(initial_state, config)

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
        )

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.COMPLAINT,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in TOOLS]},
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