import json
import re as _re
import sys
import os
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import AsyncIterator
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import SALES_AGENT_PORT, AGENT_HOST, SALES_MCP_PORT
from shared.llm import get_vertex_llm
from shared.message_utils import dicts_to_messages, messages_to_dicts
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.agent_loop import run_agent_loop, get_final_text
from shared.trace_emitter import trace_emitter

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

mcp_client = MultiServerMCPClient({
    "sales": {
        "url":       f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse",
        "transport": "sse",
    }
})

_call_complaint_agent_tool = make_agent_call_tool(
    target=AgentType.COMPLAINT,
    description=(
        "Call the complaint agent to check ticket status or complaint history. "
        "Use this when the customer mentions a ticket number or asks about an existing complaint "
        "during the sales conversation. Pass the customer_id or ticket_id in the task."
    ),
)

_call_billing_agent_tool = make_agent_call_tool(
    target=AgentType.BILLING,
    description=(
        "Call the billing agent to check a customer's balance or invoice history. "
        "Use this when the customer wants to understand current charges before committing to a plan."
    ),
)

llm       = get_vertex_llm(temperature=0, role="specialist")
mcp_tools: list = []

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
    match = _TICKET_PATTERNS.search(message)
    if not match:
        return False, ""

    cust_match   = _CUSTOMER_ID_PATTERN.search(message)
    ticket_match = _TICKET_ID_PATTERN.search(message)
    customer_id  = cust_match.group(2)   if cust_match   else "CUST-001"
    ticket_id    = ticket_match.group(2) if ticket_match else None

    task = (
        f"Check the status of ticket #{ticket_id} for customer {customer_id}."
        if ticket_id
        else f"Retrieve complaint history for customer {customer_id}."
    )

    return True, task


USER_FACING_PROMPT = """You are a friendly, knowledgeable, and enthusiastic sales agent for a telecommunications company.

CONVERSATION BEHAVIOUR:
1. Greet the user warmly on the first message. Continue naturally on subsequent turns.
2. Use tools to fetch real product data and promotions before making recommendations.
3. Always mention relevant active promotions when recommending products.
4. Use conversation history to resolve follow-up references without asking the customer
   to repeat themselves.
5. If the customer seems interested, highlight key benefits and active deals — never be pushy.
6. If the customer is ready to purchase, let them know you can connect them to the activation team.
7. Never expose raw tool output or JSON — translate everything into friendly language.
8. Close warmly if the customer says goodbye.

COLLABORATION:
- If the customer's message mentions a ticket number or complaint status, call
  call_complaint_agent in the SAME turn alongside product tools.
- If the customer mentions their current bill before committing to a plan,
  call call_billing_agent with their account_id.
- Weave all results into one seamless response."""

INTERNAL_PROMPT = """You are the sales agent responding to an internal request from another agent.
Return concise, factual product data. Do NOT greet. Just return the relevant information."""


def _get_last_human_text(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            return content if isinstance(content, str) else str(content)

    return ""


def _build_messages(req: A2ARequest) -> list:
    system_prompt = INTERNAL_PROMPT if req.is_internal else USER_FACING_PROMPT

    prior         = dicts_to_messages(req.conversation_history)
    if not prior or not isinstance(prior[-1], HumanMessage):
        prior.append(HumanMessage(content=req.user_message))

    return [SystemMessage(content=system_prompt), *prior]


def _build_tool_map(req: A2ARequest, session_id: str) -> dict:
    if req.is_internal:
        tools = list(mcp_tools)
    else:
        bound_complaint = bind_inter_agent_args(
            _call_complaint_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.SALES.value,
            history=req.conversation_history,
        )

        bound_billing = bind_inter_agent_args(
            _call_billing_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.SALES.value,
            history=req.conversation_history,
        )

        tools = [*mcp_tools, bound_complaint, bound_billing]

    return {t.name: t for t in tools if hasattr(t, "name") and t.name}


async def stream_sales_agent(req: A2ARequest) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)
    trace_emitter.emit(session_id, "agent_start", agent="sales",is_internal=req.is_internal, triggered_by=req.calling_agent or "orchestrator")
    messages = _build_messages(req)
    tool_map = _build_tool_map(req, session_id)

    if not req.is_internal:
        last_human = _get_last_human_text(messages)

        needs_check, task = _needs_complaint_check(last_human)
        if needs_check:
            bound_complaint = tool_map.get("call_complaint_agent")
            if bound_complaint:
                trace_emitter.emit(session_id, "agent_handoff", from_agent="sales", to_agent="complaint", reason=task)
                complaint_result = bound_complaint.invoke({"task": task})
                messages.insert(-1, HumanMessage(content=f"[Complaint agent result]: {complaint_result}" ))

                tool_map = {k: v for k, v in tool_map.items()
                            if k != "call_complaint_agent"}

    llm_with_tools = llm.bind_tools(list(tool_map.values()))

    async for chunk in run_agent_loop(
        llm_with_tools=llm_with_tools,
        messages=messages,
        tool_map=tool_map,
        agent_name="sales",
        session_id=session_id,
        is_internal=req.is_internal,
    ):
        yield chunk


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_tools
    mcp_url = f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse"
    print(f"Connecting to Sales MCP server at {mcp_url} ...")

    try:
        mcp_tools = await mcp_client.get_tools()

    except Exception as e:
        raise RuntimeError( f"Sales MCP server not reachable at {mcp_url}."  ) from e

    print(f"Loaded {len(mcp_tools)} MCP tools: {[t.name for t in mcp_tools]}")

    yield


app = FastAPI(title="Sales Agent", version="4.0", lifespan=lifespan)


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    if not mcp_tools:
        async def not_ready():
            yield f"event: error\ndata: {json.dumps({'message': 'Sales agent not ready.'})}\n\n"

        return StreamingResponse(not_ready(), media_type="text/event-stream",headers={"X-Accel-Buffering": "no"})

    return StreamingResponse(
        stream_sales_agent(req),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    if not mcp_tools:
        return A2AResponse(request_id=req.request_id, source_agent=AgentType.SALES,status="error", result="Sales agent not ready.")

    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(session_id, "agent_start", agent="sales", is_internal=req.is_internal, triggered_by=req.calling_agent or "orchestrator")

    final_text = ""

    async for raw in stream_sales_agent(req):
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
        source_agent=AgentType.SALES,
        status="success",
        result=final_text or "I was unable to retrieve product information.",
        metadata={"mcp_url": f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse"},
    )


@app.get("/health")
def health():
    return {
        "status":    "ok"     if mcp_tools else "starting",
        "agent":     "sales",
        "mcp_tools": "loaded" if mcp_tools else "pending",
        "tool_names": [t.name for t in mcp_tools] if mcp_tools else [],
    }


if __name__ == "__main__":
    uvicorn.run("sales_agent.main:app", host="0.0.0.0",
                port=SALES_AGENT_PORT, reload=False)