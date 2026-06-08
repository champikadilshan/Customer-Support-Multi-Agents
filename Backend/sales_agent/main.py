import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import TypedDict, Annotated, AsyncIterator
import operator

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import SALES_AGENT_PORT, AGENT_HOST, SALES_MCP_PORT
from shared.llm import get_vertex_llm


# MCP CLIENT

mcp_client = MultiServerMCPClient({
    "sales": {
        "url":       f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse",
        "transport": "sse",
    }
})


# LANGGRAPH STATE

class SalesState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# LLM

llm = get_vertex_llm(temperature=0)


# GRAPH

sales_graph: CompiledStateGraph = None
mcp_tools:   list               = []


def build_sales_graph(tools: list) -> CompiledStateGraph:
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: SalesState) -> SalesState:
        system_prompt = (
            "You are a friendly and knowledgeable sales agent. "
            "Your goal is to help customers find the best product for their needs "
            "and highlight any relevant promotions or deals. "
            "Use the available tools to fetch real product data and promotions. "
            "Be enthusiastic but not pushy. Focus on value and fit for the customer's needs. "
            "Always mention relevant active promotions when recommending products."
        )

        messages_with_system = [
            {"role": "system", "content": system_prompt},
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
        {
            "tools": "tools",
            END:     "format_response",
        },
    )

    graph.add_edge("tools",           "agent")
    graph.add_edge("format_response", END)

    return graph.compile()


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


# STREAMING GENERATOR

async def stream_sales_graph(
    req: A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    """
    Runs the sales LangGraph via astream_events and yields SSE strings.

    Filters on_chain_stream to format_response node only — that node's
    chunk is always {"final_response": "..."} which is the clean AI answer.
    All other nodes (tools, agent) are ignored to prevent raw Neo4j result
    JSON leaking as token events.
    """
    initial_state: SalesState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            # ── Tool invocation ──────────────────────────────────────────────
            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                yield _sse("tool_call", {"tool": tool_name})

            # ── Token-by-token streaming (OpenAI / future Vertex) ────────────
            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk is None:
                    continue
                text = _extract_text(chunk.content)
                if text:
                    yield _sse("token", {"text": text})

            # ── Full response in one shot (current Vertex AI behaviour) ──────
            # format_response node chunk: {"final_response": "..."}
            elif kind == "on_chain_stream" and name == "format_response":
                chunk = event.get("data", {}).get("chunk")
                if not isinstance(chunk, dict):
                    continue
                text = chunk.get("final_response", "")
                if isinstance(text, str) and text:
                    yield _sse("token", {"text": text})

        # ── Completion ───────────────────────────────────────────────────────
        yield _sse("done", {
            "request_id": req.request_id,
            "agent":      AgentType.SALES.value,
            "status":     "success",
        })

    except Exception as exc:
        yield _sse("error", {"message": str(exc)})


# FASTAPI LIFESPAN

@asynccontextmanager
async def lifespan(app: FastAPI):
    global sales_graph, mcp_tools

    mcp_url = f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse"
    print(f"Connecting to Sales MCP server at {mcp_url} ...")

    try:
        mcp_tools = await mcp_client.get_tools()
    except Exception as e:
        print(f"ERROR: Could not connect to Sales MCP server at {mcp_url}")
        print(f"       Make sure mcp_server.py is running first:")
        print(f"           python sales_agent/mcp_server.py")
        print(f"       Original error: {e}")
        raise RuntimeError(
            f"Sales MCP server is not reachable at {mcp_url}. "
            f"Start it with: python sales_agent/mcp_server.py"
        ) from e

    tool_names = [t.name for t in mcp_tools]
    print(f"Loaded {len(mcp_tools)} tools from MCP server: {tool_names}")

    sales_graph = build_sales_graph(mcp_tools)
    print("Sales agent graph built and ready.")

    yield


# FASTAPI

app = FastAPI(title="Sales Agent", version="1.0", lifespan=lifespan)


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    if sales_graph is None:
        async def not_ready():
            yield _sse("error", {
                "message": "Sales agent is not ready yet. MCP tools are still loading."
            })
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

    initial_state: SalesState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    result = await sales_graph.ainvoke(initial_state)

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.SALES,
        status="success",
        result=result["final_response"],
        metadata={
            "tools_source": "mcp",
            "mcp_url":      f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse",
        },
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
    import uvicorn

    uvicorn.run(
        "sales_agent.main:app",
        host="0.0.0.0",
        port=SALES_AGENT_PORT,
        reload=False,
    )