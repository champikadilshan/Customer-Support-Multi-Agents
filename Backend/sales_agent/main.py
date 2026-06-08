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


# =============================================================================
# MCP CLIENT — connects to the MCP server via SSE transport
# Tools are discovered from the MCP server, NOT defined locally.
# =============================================================================

mcp_client = MultiServerMCPClient({
    "sales": {
        "url":       f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse",
        "transport": "sse",
    }
})


# =============================================================================
# LANGGRAPH STATE
# messages uses operator.add so each node appends rather than overwrites
# =============================================================================

class SalesState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# =============================================================================
# LLM
# =============================================================================

llm = get_vertex_llm(temperature=0)


# =============================================================================
# GRAPH — built async so tools can be fetched from MCP server at startup
# =============================================================================

sales_graph: CompiledStateGraph = None    # populated in lifespan
mcp_tools:   list               = []     # kept so /health can report tool names


def build_sales_graph(tools: list) -> CompiledStateGraph:
    """
    Build the LangGraph with tools loaded from the MCP server.
    Called once at startup after MCP tools are fetched.

    The streaming path (astream_events) works identically whether tools
    come from @tool decorators or from the MCP adapter — LangGraph fires
    on_tool_start / on_chat_model_stream events the same way in both cases.

    Graph shape:

                START
                  |
              agent_node  <--------------+
                  |                      |
      tools_condition (conditional edge) |
          +-------+-------+             |
       "tools"         END              |
          |              |              |
       tool_node    format_response     |
          |              |              |
          +--------------+--------------+
                         |
                        END
    """
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: SalesState) -> SalesState:
        """
        Core ReAct node.
        LLM decides whether to call a tool or give a final response.
        Typical flow for a sales enquiry:
          1. Calls get_product_catalog to find relevant products
          2. Calls get_active_promotions to check for applicable deals
          3. Optionally calls check_product_availability for a specific product
          4. Produces a helpful, persuasive sales response
        Tools are provided by the MCP server — not defined in this file.
        """
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
        """
        Extracts the final AI answer after the ReAct loop completes.
        Still used by the non-streaming /process endpoint.
        """
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


# =============================================================================
# SSE HELPERS
# =============================================================================

def _sse(event: str, data: dict) -> str:
    """
    Format a single SSE frame.
    The double newline at the end is required by the SSE spec —
    it signals the end of one event to the client.

    Example output:
        event: tool_call
        data: {"tool": "get_product_catalog"}

    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_sales_graph(
    req: A2ARequest,
    graph: CompiledStateGraph,
) -> AsyncIterator[str]:
    """
    Async generator that runs the sales LangGraph via astream_events
    and yields SSE-formatted strings.

    MCP tools fire the same LangGraph events as locally-defined @tool
    functions — on_tool_start, on_tool_end, on_chat_model_stream — so
    no special handling is needed for the MCP adapter layer.

    Event types emitted:
      - tool_call : fired when the LLM decides to invoke an MCP tool.
                    Each MCP tool call goes over the network to the MCP
                    server (which then queries Neo4j), so tool_call events
                    are a useful "still working" signal to the UI.
      - token     : fired for every text chunk the LLM streams.
                    Carries {"text": "<chunk>"}.
      - done      : fired once after the graph finishes.
                    Carries request_id, agent name, and status.
      - error     : fired if an exception is raised mid-stream.
                    Carries {"message": "<error text>"}.

    Typical tool call sequence for a sales enquiry:
      on_tool_start → get_product_catalog      (MCP → Neo4j)
      on_tool_start → get_active_promotions    (MCP → Neo4j)
      on_tool_start → check_product_availability  (optional, MCP → Neo4j)
      on_chat_model_stream → token … token … token
      done
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

            # ── Tool invocation ──────────────────────────────────────────────
            # Fired once per MCP tool call, before the tool executes.
            # Each call crosses the network to the MCP server and then to
            # Neo4j, so the UI has real latency to fill — surface the name.
            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                yield _sse("tool_call", {"tool": tool_name})

            # ── Streaming LLM tokens ─────────────────────────────────────────
            # on_chat_model_stream fires once per token chunk.
            # Skip list-form content (mid-tool-call scaffolding frames).
            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk is None:
                    continue

                content = chunk.content
                if isinstance(content, str) and content:
                    yield _sse("token", {"text": content})
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield _sse("token", {"text": text})

        # ── Completion ───────────────────────────────────────────────────────
        yield _sse("done", {
            "request_id": req.request_id,
            "agent":      AgentType.SALES.value,
            "status":     "success",
        })

    except Exception as exc:
        # Surface the error as an SSE event so the orchestrator can handle
        # it gracefully rather than seeing a broken stream with no explanation.
        yield _sse("error", {"message": str(exc)})


# =============================================================================
# FASTAPI LIFESPAN — fetch MCP tools and build graph before serving requests
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup:
      1. Connect to the MCP server via SSE
      2. Fetch all tools the MCP server exposes
      3. Build the LangGraph with those tools bound to the LLM

    Both /process and /process/stream share the same compiled graph.
    The streaming generator (stream_sales_graph) uses astream_events on
    the same graph object — no separate graph is needed for streaming.

    NOTE: the MCP server (sales_agent/mcp_server.py) MUST be running
    before this agent starts, otherwise startup will fail with a
    connection error.
    """
    global sales_graph, mcp_tools

    mcp_url = f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse"
    print(f"Connecting to Sales MCP server at {mcp_url} ...")

    try:
        # langchain-mcp-adapters >= 0.1.0: call get_tools() directly, no context manager
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

    yield   # server is running — handle requests


# =============================================================================
# FASTAPI — A2A endpoints
# =============================================================================

app = FastAPI(title="Sales Agent", version="1.0", lifespan=lifespan)


# -----------------------------------------------------------------------------
# NEW — streaming endpoint
# The orchestrator calls this and reads the SSE stream token by token.
# Guards against the graph not being ready yet (MCP still loading).
# -----------------------------------------------------------------------------
@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    """
    Streaming A2A endpoint.
    Runs the sales ReAct graph and pushes SSE events as they happen:
      - tool_call events when an MCP tool is about to execute
            (each call crosses the network to the MCP server + Neo4j)
      - token     events for each LLM output chunk
      - done      event when the graph finishes
      - error     event on failure

    Returns a 503 JSON error immediately if the MCP tools haven't loaded yet
    so the orchestrator gets a clear signal rather than a broken stream.
    """
    if sales_graph is None:
        # Return a plain error SSE stream rather than raising an HTTP error —
        # keeps the response format consistent for the orchestrator.
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
        # X-Accel-Buffering: no tells nginx not to buffer chunks.
        headers={"X-Accel-Buffering": "no"},
    )


# -----------------------------------------------------------------------------
# KEPT — original blocking endpoint
# Still available so the orchestrator can fall back to non-streaming mode
# during a migration, or for callers that don't support SSE.
# -----------------------------------------------------------------------------
@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    """
    Original blocking A2A endpoint — unchanged.
    Runs the full graph and returns a single A2AResponse JSON body.
    """
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
        "status":     "ok"      if sales_graph is not None else "starting",
        "agent":      "sales",
        "mcp_tools":  "loaded"  if sales_graph is not None else "pending",
        "tool_names": [t.name for t in mcp_tools] if mcp_tools else [],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sales_agent.main:app",
        host="0.0.0.0",
        port=SALES_AGENT_PORT,
        reload=False,   # reload=False because lifespan + global state
    )