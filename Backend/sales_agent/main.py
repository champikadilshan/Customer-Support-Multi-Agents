from fastapi import FastAPI
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, BaseMessage
from typing import TypedDict, Annotated
import operator

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import SALES_AGENT_PORT
from shared.llm import get_vertex_llm


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@tool
def get_product_catalog(category: str) -> list[dict]:
    """
    Retrieve products available in a given category with descriptions and prices.
    Use this when the user asks about what products are available,
    wants to compare options, or is looking for something specific.
    Categories: internet, mobile, tv, bundle.
    Pass 'all' to get every product across all categories.
    """
    catalog = {
        "internet": [
            {"id": "INT-001", "name": "Fiber Basic",    "speed": "100 Mbps", "price": "$39.99/mo",  "description": "Great for light browsing and streaming"},
            {"id": "INT-002", "name": "Fiber Pro",      "speed": "500 Mbps", "price": "$59.99/mo",  "description": "Perfect for remote work and HD streaming"},
            {"id": "INT-003", "name": "Fiber Ultra",    "speed": "1 Gbps",   "price": "$89.99/mo",  "description": "Best for heavy users, gamers, and large households"},
        ],
        "mobile": [
            {"id": "MOB-001", "name": "Starter SIM",   "data": "5 GB",      "price": "$15.00/mo",  "description": "For light mobile users"},
            {"id": "MOB-002", "name": "Standard SIM",  "data": "20 GB",     "price": "$29.00/mo",  "description": "Balanced data plan for everyday use"},
            {"id": "MOB-003", "name": "Unlimited SIM", "data": "Unlimited", "price": "$45.00/mo",  "description": "No limits — calls, texts, and data"},
        ],
        "tv": [
            {"id": "TV-001",  "name": "Basic TV",      "channels": "50+",   "price": "$25.00/mo",  "description": "Essential channels including local and news"},
            {"id": "TV-002",  "name": "Entertainment", "channels": "150+",  "price": "$45.00/mo",  "description": "Movies, sports, and lifestyle channels"},
            {"id": "TV-003",  "name": "Premium TV",    "channels": "300+",  "price": "$65.00/mo",  "description": "Full package with premium and international channels"},
        ],
        "bundle": [
            {"id": "BND-001", "name": "Home Bundle",   "includes": "Fiber Basic + Basic TV",         "price": "$54.99/mo",  "saving": "Save $10/mo"},
            {"id": "BND-002", "name": "Pro Bundle",    "includes": "Fiber Pro + Entertainment + SIM", "price": "$99.99/mo",  "saving": "Save $34/mo"},
        ],
    }

    if category == "all":
        return [item for products in catalog.values() for item in products]

    return catalog.get(category, [{"error": f"Unknown category: {category}. Use: internet, mobile, tv, bundle, all"}])


@tool
def get_active_promotions() -> list[dict]:
    """
    Retrieve all currently active promotions, discounts, and special offers.
    Use this when the user asks about deals, discounts, promotions,
    or ways to save money.
    """
    # Simulated promotions DB
    return [
        {
            "promo_id":   "PROMO-SUMMER24",
            "title":      "Summer Upgrade Deal",
            "description": "Upgrade to Fiber Pro and get 3 months at half price",
            "discount":   "50% off for 3 months",
            "expires":    "2024-08-31",
            "applicable_to": ["INT-002"],
        },
        {
            "promo_id":   "PROMO-BUNDLE10",
            "title":      "Bundle & Save",
            "description": "Take any bundle and get an extra $10 off per month",
            "discount":   "$10/mo additional discount",
            "expires":    "2024-12-31",
            "applicable_to": ["BND-001", "BND-002"],
        },
        {
            "promo_id":   "PROMO-NEWSIM",
            "title":      "New SIM Offer",
            "description": "First month free when you sign up for any mobile plan",
            "discount":   "First month free",
            "expires":    "2024-07-31",
            "applicable_to": ["MOB-001", "MOB-002", "MOB-003"],
        },
    ]


@tool
def check_product_availability(product_id: str) -> dict:
    """
    Check whether a specific product is currently available and
    how quickly it can be activated.
    Use this when the user is ready to purchase or wants to know
    if a product is in stock / can be set up.
    """
    # Simulated availability DB
    availability = {
        "INT-001": {"available": True,  "activation": "Same day",      "contract": "No contract"},
        "INT-002": {"available": True,  "activation": "Same day",      "contract": "12-month option for discount"},
        "INT-003": {"available": True,  "activation": "Next business day", "contract": "12-month option for discount"},
        "MOB-001": {"available": True,  "activation": "SIM delivered in 2-3 days", "contract": "No contract"},
        "MOB-002": {"available": True,  "activation": "SIM delivered in 2-3 days", "contract": "No contract"},
        "MOB-003": {"available": True,  "activation": "SIM delivered in 2-3 days", "contract": "No contract"},
        "TV-001":  {"available": True,  "activation": "Same day (streaming app)",  "contract": "No contract"},
        "TV-002":  {"available": True,  "activation": "Same day (streaming app)",  "contract": "No contract"},
        "TV-003":  {"available": False, "activation": "Coming soon",    "contract": "N/A"},
        "BND-001": {"available": True,  "activation": "Same day",      "contract": "12-month recommended"},
        "BND-002": {"available": True,  "activation": "Next business day", "contract": "12-month recommended"},
    }

    return availability.get(
        product_id,
        {"available": False, "activation": "N/A", "contract": "N/A", "error": "Product ID not found"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# LANGGRAPH STATE
# ══════════════════════════════════════════════════════════════════════════════

class SalesState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# ══════════════════════════════════════════════════════════════════════════════
# LLM — bind all tools
# ══════════════════════════════════════════════════════════════════════════════

TOOLS = [get_product_catalog, get_active_promotions, check_product_availability]

llm = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def agent_node(state: SalesState) -> SalesState:
    """
    Core ReAct node.
    LLM decides whether to call a tool or give a final response.
    Typical flow for a sales enquiry:
      1. Calls get_product_catalog to find relevant products
      2. Calls get_active_promotions to check for applicable deals
      3. Optionally calls check_product_availability for a specific product
      4. Produces a helpful, persuasive sales response
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


# ══════════════════════════════════════════════════════════════════════════════
# BUILD GRAPH
# ══════════════════════════════════════════════════════════════════════════════

def build_sales_graph() -> CompiledStateGraph:
    """
    Graph shape:
                    START
                      │
                  agent_node  ◄──────────────┐
                      │                       │
          tools_condition (conditional edge)  │
              ┌─────┴─────┐                  │
           "tools"    "end"                  │
              │            │                  │
          tool_node    format_response        │
              │            │                  │
              └────────────┘──────────────────┘
                            │
                           END
    """
    graph = StateGraph(SalesState)

    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(TOOLS))
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


# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI — A2A endpoint
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Sales Agent", version="1.0")
sales_graph: CompiledStateGraph = build_sales_graph()


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    """
    A2A entry point — called by the Intent Detector orchestrator.
    """
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
        metadata={"tools_available": [t.name for t in TOOLS]},
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "sales"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sales_agent.main:app",
        host="0.0.0.0",
        port=SALES_AGENT_PORT,
        reload=True,
    )