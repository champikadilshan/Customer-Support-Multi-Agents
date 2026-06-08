import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import TypedDict, Annotated
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

sales_graph: CompiledStateGraph = None   # populated in lifespan


def build_sales_graph(tools: list) -> CompiledStateGraph:
    """
    Build the LangGraph with tools loaded from the MCP server.
    Called once at startup after MCP tools are fetched.

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
# FASTAPI LIFESPAN — fetch MCP tools and build graph before serving requests
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup:
      1. Connect to the MCP server via SSE
      2. Fetch all tools the MCP server exposes
      3. Build the LangGraph with those tools bound to the LLM

    This is the key difference from the old approach:
      - Old: tools defined locally with @tool, hardcoded httpx calls
      - New: tools discovered dynamically from the MCP server
    """
    global sales_graph

    print("Connecting to Sales MCP server and fetching tools...")

    # langchain-mcp-adapters >= 0.1.0: call get_tools() directly, no context manager
    tools = await mcp_client.get_tools()
    tool_names = [t.name for t in tools]
    print(f"Loaded {len(tools)} tools from MCP server: {tool_names}")

    sales_graph = build_sales_graph(tools)
    print("Sales agent graph built and ready.")

    yield   # server is running



# =============================================================================
# FASTAPI — A2A endpoint
# =============================================================================

app = FastAPI(title="Sales Agent", version="1.0", lifespan=lifespan)


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    """
    A2A entry point — called by the Intent Detector orchestrator.
    Receives an A2ARequest, runs the sales ReAct graph,
    returns an A2AResponse.
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
        metadata={"tools_source": "mcp", "mcp_url": f"http://{AGENT_HOST}:{SALES_MCP_PORT}/sse"},
    )


@app.get("/health")
def health():
    return {
        "status":    "ok" if sales_graph is not None else "starting",
        "agent":     "sales",
        "mcp_tools": "loaded" if sales_graph is not None else "pending",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sales_agent.main:app",
        host="0.0.0.0",
        port=SALES_AGENT_PORT,
        reload=False,   # reload=False because lifespan + global state
    )