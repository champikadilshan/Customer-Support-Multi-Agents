import json
import sys
import os
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from typing import AsyncIterator

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import SALES_AGENT_PORT, AGENT_HOST, SALES_MCP_PORT
from shared.llm import get_vertex_llm
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.agent_runner import stream_agent_events
from shared.trace_emitter import trace_emitter

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

mcp_client = MultiServerMCPClient({
    "sales": {
        "url":       f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse",
        "transport": "sse",
    }
})

mcp_tools: list = []   # populated in lifespan


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

COLLABORATION — A2A sub-agent calls (use these tools when YOU need the data):
- call_complaint_agent: call this when the customer mentions a ticket number,
  asks about a specific complaint, or you need complaint context to answer a
  sales question. Do NOT call this just because the user asked about complaints
  in general — the orchestrator handles pure complaint requests directly.
- call_billing_agent: call this when the customer mentions their current bill
  or account balance and you need that data before recommending a plan.
- Only make A2A calls when the data is genuinely needed to complete YOUR task.
  If the orchestrator has already handled the complaint/billing part separately,
  do not duplicate that call.
- Weave all results into one seamless response."""

INTERNAL_PROMPT = """You are the sales agent responding to an internal request from another agent.
Return concise, factual product data. Do NOT greet. Just return the relevant information."""


llm          = get_vertex_llm(temperature=0, role="specialist")
_checkpointer = InMemorySaver()


def _build_agent(req: A2ARequest, session_id: str):
    if req.is_internal:
        tools  = list(mcp_tools)
        prompt = INTERNAL_PROMPT

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

        tools  = [*mcp_tools, bound_complaint, bound_billing]
        prompt = USER_FACING_PROMPT

    return create_agent(
        llm,
        tools=tools,
        system_prompt=prompt,
        checkpointer=_checkpointer,
        name="sales",
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


async def stream_sales_agent(req: A2ARequest) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)

    trace_emitter.emit(
        session_id, "agent_start", agent="sales",
        is_internal=req.is_internal,
        triggered_by=req.calling_agent or "orchestrator",
    )

    messages = _build_messages(req)
    agent = _build_agent(req, session_id)

    async for chunk in stream_agent_events(
        agent=agent,
        messages=messages,
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
        raise RuntimeError(f"Sales MCP server not reachable at {mcp_url}.") from e

    print(f"Loaded {len(mcp_tools)} MCP tools: {[t.name for t in mcp_tools]}")

    yield


app = FastAPI(title="Sales Agent", version="5.0", lifespan=lifespan)


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    if not mcp_tools:
        async def not_ready():
            yield f"event: error\ndata: {json.dumps({'message': 'Sales agent not ready.'})}\n\n"
        return StreamingResponse(not_ready(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
    return StreamingResponse(
        stream_sales_agent(req),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    if not mcp_tools:
        return A2AResponse(
            request_id=req.request_id, source_agent=AgentType.SALES,
            status="error", result="Sales agent not ready.",
        )

    session_id = req.context.get("session_id", req.request_id)
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
        "status":     "ok"     if mcp_tools else "starting",
        "agent":      "sales",
        "mcp_tools":  "loaded" if mcp_tools else "pending",
        "tool_names": [t.name for t in mcp_tools] if mcp_tools else [],
    }


if __name__ == "__main__":
    uvicorn.run(
        "sales_agent.main:app",
        host="0.0.0.0",
        port=SALES_AGENT_PORT,
        reload=False,
    )