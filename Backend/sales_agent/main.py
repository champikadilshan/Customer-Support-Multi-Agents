"""
sales_agent/main.py  (v3 — multi-agent collaboration + trace)
"""

import json
import operator
import sys
import os
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import TypedDict, Annotated, AsyncIterator

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import SALES_AGENT_PORT, AGENT_HOST, SALES_MCP_PORT
from shared.llm import get_vertex_llm
from shared.message_utils import dicts_to_messages, messages_to_dicts
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.trace_emitter import trace_emitter

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# ── MCP client ────────────────────────────────────────────────────────────────

mcp_client = MultiServerMCPClient({
    "sales": {
        "url":       f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse",
        "transport": "sse",
    }
})

# ── LangGraph state ───────────────────────────────────────────────────────────

class SalesState(TypedDict):
    request_id:     str
    user_message:   str
    session_id:     str
    is_internal:    bool
    calling_agent:  str
    history:        list[dict]
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str

# ── LLM ───────────────────────────────────────────────────────────────────────

llm = get_vertex_llm(temperature=0)

# Runtime globals set in lifespan
sales_graph: CompiledStateGraph = None
mcp_tools:   list               = []

# ── Inter-agent tools (unbound) ───────────────────────────────────────────────

_call_complaint_agent_tool = make_agent_call_tool(
    target=AgentType.COMPLAINT,
    description=(
        "Call the complaint agent to check the status of an existing ticket or retrieve "
        "a customer's complaint history. Use this when the customer asks about an open issue "
        "or ticket during a sales conversation. Pass the customer_id or ticket_id in the task."
    ),
)

_call_billing_agent_tool = make_agent_call_tool(
    target=AgentType.BILLING,
    description=(
        "Call the billing agent to check a customer's current balance, invoice history, "
        "or payment methods. Use this when the customer wants to understand their current "
        "charges before committing to a new plan, or when a credit needs to be confirmed. "
        "Pass the account_id in the task."
    ),
)

# ── System prompts ────────────────────────────────────────────────────────────

USER_FACING_PROMPT = """You are a friendly, knowledgeable, and enthusiastic sales agent for a telecommunications company.

CONVERSATION BEHAVIOUR:
1. Greet the user warmly on the first message. Continue naturally on subsequent turns.
2. Use tools to fetch real product data and promotions before making recommendations.
3. Always mention relevant active promotions when recommending products.
4. Use conversation history to resolve follow-up references ("the cheaper one", "add mobile to that")
   without asking the customer to repeat themselves.
5. If the customer seems interested, highlight the key benefit and any active deal — never be pushy.
6. If the customer is ready to purchase, let them know you can connect them to the activation team.
7. Never expose raw tool output or JSON — translate everything into warm, conversational language.
8. Close warmly if the customer says goodbye.

COLLABORATION — STRICT RULES:
- If the customer's message mentions a ticket number, ticket status, complaint, or customer ID
  alongside a product question, you MUST call call_complaint_agent in the SAME turn.
  Do this BEFORE or AFTER fetching products — but do it in the same response.
  Example: "show me plans and check ticket 1" → call get_product_catalog AND call_complaint_agent.
- If the customer mentions their current bill or charges before committing to a plan,
  call call_billing_agent with their account_id.
- Weave all results into one seamless response — never tell the customer you called another agent.
- Only skip inter-agent calls if the customer's message is purely about products."""

import re as _re

# Keywords that reliably signal a ticket status check is needed
_TICKET_PATTERNS = _re.compile(
    r"ticket\s*(number|#|no\.?)?\s*\d+|check\s*(my\s*)?(ticket|complaint)|"
    r"status\s*of\s*(my\s*)?(ticket|complaint)|complaint\s*(history|status)",
    _re.IGNORECASE,
)
_CUSTOMER_ID_PATTERN = _re.compile(
    r"customer\s*(id\s*)?[:\s]*(CUST-\d+)", _re.IGNORECASE
)
_TICKET_ID_PATTERN = _re.compile(
    r"ticket\s*(number|#|no\.?)?\s*(\d+)", _re.IGNORECASE
)


def _needs_complaint_check(message: str) -> tuple[bool, str]:
    """
    Return (True, task_description) if the message contains a ticket/complaint
    check request alongside a product question.
    """
    match = _TICKET_PATTERNS.search(message)
    print(f"[TICKET_PATTERN] input={repr(message[:100])}")
    print(f"[TICKET_PATTERN] match={match}")
    if not match:
        return False, ""

    cust_match   = _CUSTOMER_ID_PATTERN.search(message)
    ticket_match = _TICKET_ID_PATTERN.search(message)
    print(f"[TICKET_PATTERN] cust_match={cust_match}, ticket_match={ticket_match}")

    customer_id = cust_match.group(2)   if cust_match   else "CUST-001"
    ticket_id   = ticket_match.group(2) if ticket_match else None

    if ticket_id:
        task = f"Check the status of ticket #{ticket_id} for customer {customer_id}."
    else:
        task = f"Retrieve complaint history for customer {customer_id}."

    return True, task

def build_sales_graph(mcp_tool_list: list) -> CompiledStateGraph:

    def agent_node(state: SalesState) -> SalesState:
        is_internal   = state.get("is_internal", False)
        session_id    = state.get("session_id", "")
        history       = state.get("history", [])
        system_prompt = INTERNAL_PROMPT if is_internal else USER_FACING_PROMPT

        if is_internal:
            all_tools = mcp_tool_list
        else:
            bound_complaint = bind_inter_agent_args(
                _call_complaint_agent_tool,
                session_id=session_id,
                calling_agent=AgentType.SALES.value,
                history=history,
            )
            bound_billing = bind_inter_agent_args(
                _call_billing_agent_tool,
                session_id=session_id,
                calling_agent=AgentType.SALES.value,
                history=history,
            )
            all_tools = [*mcp_tool_list, bound_complaint, bound_billing]

        # ── Pre-flight: deterministic inter-agent call detection ──────────────
        extra_messages = []
        if not is_internal:
            # Use the last HumanMessage from the messages list — state["user_message"]
            # is the original first-turn value and never updates across turns.
            from langchain_core.messages import HumanMessage as _HM
            last_human = ""
            for msg in reversed(state["messages"]):
                if isinstance(msg, _HM) and msg.content:
                    last_human = msg.content if isinstance(msg.content, str) else str(msg.content)
                    break
            print(f"[SALES PRE-FLIGHT] last_human={repr(last_human[:80])}")
            needs_check, task = _needs_complaint_check(last_human)
            print(f"[SALES PRE-FLIGHT] needs_check={needs_check}, task={repr(task)}")
            if needs_check:
                print(f"[SALES PRE-FLIGHT] Calling complaint agent: {task}")
                from shared.trace_emitter import trace_emitter as _te
                _te.emit(session_id, "agent_handoff",
                         from_agent="sales", to_agent="complaint",
                         reason=task)
                complaint_result = bound_complaint.invoke({"task": task})
                print(f"[SALES PRE-FLIGHT] Result: {repr(str(complaint_result)[:120])}")
                extra_messages = [
                    {
                        "role":    "system",
                        "content": f"[Complaint agent result for this turn]: {complaint_result}"
                    }
                ]
                # Remove call_complaint_agent from tools so LLM doesn't call it again
                all_tools = [t for t in all_tools
                             if getattr(t, "name", "") != "call_complaint_agent"]

        llm_with_tools = llm.bind_tools(all_tools)
        messages_with_system = [
            {"role": "system", "content": system_prompt},
            *extra_messages,
            *state["messages"],
        ]
        response = llm_with_tools.invoke(messages_with_system)
        return {"messages": [response]}

    def format_response_node(state: SalesState) -> SalesState:
        for msg in reversed(state["messages"]):
            if hasattr(msg, "content") and msg.content:
                final = msg.content
                break
        else:
            final = "I was unable to retrieve product information at this time. Please try again."
        return {**state, "final_response": final}

    all_possible_tools = [*mcp_tool_list, _call_complaint_agent_tool, _call_billing_agent_tool]

    graph = StateGraph(SalesState)
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

async def stream_sales_graph(
    req: A2ARequest, graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="sales",
                       is_internal=req.is_internal,
                       triggered_by=req.calling_agent or "orchestrator")

    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: SalesState = {
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
                                   agent="sales", tool=tool_name)
                if not req.is_internal:
                    yield _sse("tool_call", {"tool": tool_name})

            elif kind == "on_tool_end":
                trace_emitter.emit(session_id, "tool_end",
                                   agent="sales", tool=event.get("name", ""))

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

        trace_emitter.emit(session_id, "agent_end", agent="sales",
                           status="success", is_internal=req.is_internal)

        if not req.is_internal:
            yield _sse("done", {
                "request_id": req.request_id,
                "agent":      AgentType.SALES.value,
                "status":     "success",
            })

    except Exception as exc:
        trace_emitter.emit(session_id, "error", agent="sales", message=str(exc))
        if not req.is_internal:
            yield _sse("error", {"message": str(exc)})


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global sales_graph, mcp_tools
    mcp_url = f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse"
    print(f"Connecting to Sales MCP server at {mcp_url} ...")
    try:
        mcp_tools = await mcp_client.get_tools()
    except Exception as e:
        raise RuntimeError(
            f"Sales MCP server not reachable at {mcp_url}. "
            "Start with: python sales_agent/mcp_server.py"
        ) from e

    tool_names  = [t.name for t in mcp_tools]
    print(f"Loaded {len(mcp_tools)} MCP tools: {tool_names}")
    sales_graph = build_sales_graph(mcp_tools)
    print("Sales agent graph built and ready.")
    yield


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Sales Agent", version="3.0", lifespan=lifespan)


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    if sales_graph is None:
        async def not_ready():
            yield _sse("error", {"message": "Sales agent not ready yet."})
        return StreamingResponse(not_ready(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})
    return StreamingResponse(
        stream_sales_graph(req, sales_graph),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    if sales_graph is None:
        return A2AResponse(request_id=req.request_id, source_agent=AgentType.SALES,
                           status="error", result="Sales agent not ready yet.")

    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="sales",
                       is_internal=req.is_internal,
                       triggered_by=req.calling_agent or "orchestrator")

    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: SalesState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "session_id":     session_id,
        "is_internal":    req.is_internal,
        "calling_agent":  req.calling_agent or "",
        "history":        req.conversation_history,
        "messages":       prior_messages,
        "final_response": "",
    }

    result        = await sales_graph.ainvoke(initial_state)
    prior_len     = len(prior_messages)
    new_msgs_dict = messages_to_dicts(result["messages"][prior_len:])

    trace_emitter.emit(session_id, "agent_end", agent="sales",
                       status="success", is_internal=req.is_internal)

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.SALES,
        status="success",
        result=result["final_response"],
        metadata={"tools_source": "mcp", "mcp_url": f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse"},
        new_messages=new_msgs_dict,
    )


@app.get("/health")
def health():
    return {
        "status":     "ok"     if sales_graph is not None else "starting",
        "agent":      "sales",
        "mcp_tools":  "loaded" if sales_graph is not None else "pending",
        "tool_names": [t.name for t in mcp_tools] if mcp_tools else [],
    }


if __name__ == "__main__":
    uvicorn.run("sales_agent.main:app", host="0.0.0.0",
                port=SALES_AGENT_PORT, reload=False)