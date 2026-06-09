"""
sales_agent/main.py
-------------------
Sales agent — updated for multi-turn conversation sessions.

Key changes vs original
------------------------
1. A2ARequest.conversation_history seeds the LangGraph state so the LLM
   has full context across turns (e.g. "what about the cheaper one?" resolves
   correctly against what was already discussed).

2. System prompt updated with natural-conversation behavioural instructions.

3. A2AResponse.new_messages carries messages produced this turn back to the
   orchestrator for session storage.
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
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# ── LLM ───────────────────────────────────────────────────────────────────────

llm = get_vertex_llm(temperature=0)

# Runtime globals set in lifespan
sales_graph: CompiledStateGraph = None
mcp_tools:   list               = []


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a friendly, knowledgeable, and enthusiastic sales agent for a telecommunications company.

CONVERSATION BEHAVIOUR — follow these rules exactly:
1. Greet the user warmly on the very first message. On subsequent turns, continue
   naturally without re-introducing yourself.
2. Use the available tools to fetch real product data and promotions before
   making any recommendations — never guess prices or availability.
3. Always mention relevant active promotions when recommending products.
4. Use the conversation history to resolve follow-up references such as
   "what about the cheaper one?" or "can I add a mobile plan to that?" without
   asking the customer to repeat themselves.
5. If the customer seems interested in a product, guide them towards a decision
   by highlighting the key benefit and any active deal — but never be pushy.
6. If the customer is ready to purchase or asks how to sign up, let them know
   you can connect them to the support team to arrange activation.
7. Never expose raw tool output or JSON to the customer — translate everything
   into warm, conversational language.
8. Keep responses concise; use bullet points only when comparing multiple products.
9. If the customer says goodbye or thanks you, close the conversation warmly."""


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_sales_graph(tools: list) -> CompiledStateGraph:
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: SalesState) -> SalesState:
        messages_with_system = [
            {"role": "system", "content": SYSTEM_PROMPT},
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

    graph = StateGraph(SalesState)
    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(tools))
    graph.add_node("format_response", format_response_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: "format_response"},
    )
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
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


# ── Streaming generator ───────────────────────────────────────────────────────

async def stream_sales_graph(
    req:   A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    # Reconstruct full message history
    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: SalesState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       prior_messages,
        "final_response": "",
    }

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
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

        yield _sse("done", {
            "request_id": req.request_id,
            "agent":      AgentType.SALES.value,
            "status":     "success",
        })

    except Exception as exc:
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
        print(f"ERROR: Could not connect to Sales MCP server at {mcp_url}")
        print(f"  Make sure mcp_server.py is running first.")
        print(f"  Original error: {e}")
        raise RuntimeError(
            f"Sales MCP server is not reachable at {mcp_url}. "
            "Start it with: python sales_agent/mcp_server.py"
        ) from e

    tool_names = [t.name for t in mcp_tools]
    print(f"Loaded {len(mcp_tools)} tools from MCP server: {tool_names}")
    sales_graph = build_sales_graph(mcp_tools)
    print("Sales agent graph built and ready.")

    yield


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Sales Agent", version="2.0", lifespan=lifespan)


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    if sales_graph is None:
        async def not_ready():
            yield _sse("error", {"message": "Sales agent is not ready yet. MCP tools are still loading."})
        return StreamingResponse(
            not_ready(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        stream_sales_graph(req, sales_graph),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    if sales_graph is None:
        return A2AResponse(
            request_id=req.request_id,
            source_agent=AgentType.SALES,
            status="error",
            result="Sales agent is not ready yet. MCP tools are still loading.",
        )

    prior_messages = dicts_to_messages(req.conversation_history)
    if not prior_messages or not isinstance(prior_messages[-1], HumanMessage):
        prior_messages.append(HumanMessage(content=req.user_message))

    initial_state: SalesState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       prior_messages,
        "final_response": "",
    }

    result = await sales_graph.ainvoke(initial_state)

    prior_len     = len(prior_messages)
    new_msgs_dict = messages_to_dicts(result["messages"][prior_len:])

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.SALES,
        status="success",
        result=result["final_response"],
        metadata={
            "tools_source": "mcp",
            "mcp_url":      f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse",
        },
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
    uvicorn.run(
        "sales_agent.main:app",
        host="0.0.0.0",
        port=SALES_AGENT_PORT,
        reload=False,
    )