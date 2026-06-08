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
from shared.config import BILLING_AGENT_PORT
from shared.llm import get_vertex_llm

# ══════════════════════════════════════════════════════════════════════════════
# TOOLS  — decorated with @tool so LLM can discover and call them
# In production, replace the simulated data with real DB / API calls
# ══════════════════════════════════════════════════════════════════════════════

@tool
def get_account_balance(account_id: str) -> dict:
    """
    Fetch the current account balance, payment due date, and payment status
    for a given account ID.
    Use this when the user asks about their balance, how much they owe,
    or when their next payment is due.
    """
    # Simulated DB response
    return {
        "account_id":    account_id,
        "balance_due":   "$245.00",
        "due_date":      "2024-07-15",
        "payment_status": "Pending",
        "last_payment":  "$245.00 on 2024-06-15",
    }


@tool
def get_invoice_history(account_id: str) -> list[dict]:
    """
    Retrieve the last 5 invoices for a given account ID.
    Use this when the user asks about past invoices, billing history,
    or wants to see previous charges.
    """
    # Simulated DB response
    return [
        {"invoice_id": "INV-001", "date": "2024-06-01", "amount": "$245.00", "status": "Paid"},
        {"invoice_id": "INV-002", "date": "2024-05-01", "amount": "$245.00", "status": "Paid"},
        {"invoice_id": "INV-003", "date": "2024-04-01", "amount": "$220.00", "status": "Paid"},
        {"invoice_id": "INV-004", "date": "2024-03-01", "amount": "$220.00", "status": "Paid"},
        {"invoice_id": "INV-005", "date": "2024-02-01", "amount": "$200.00", "status": "Paid"},
    ]


@tool
def get_payment_methods(account_id: str) -> dict:
    """
    Retrieve the saved payment methods on file for a given account ID.
    Use this when the user asks about their saved cards, bank accounts,
    or wants to know how they can pay.
    """
    # Simulated DB response
    return {
        "account_id": account_id,
        "payment_methods": [
            {"type": "Visa",        "last4": "4242", "expiry": "12/26", "default": True},
            {"type": "Bank Account","last4": "9876", "bank":   "Chase",  "default": False},
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# LANGGRAPH STATE
# messages uses operator.add so each node appends rather than overwrites
# ══════════════════════════════════════════════════════════════════════════════

class BillingState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# ══════════════════════════════════════════════════════════════════════════════
# LLM — bind all tools so LLM knows it can call them
# ══════════════════════════════════════════════════════════════════════════════

TOOLS = [get_account_balance, get_invoice_history, get_payment_methods]

llm = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def agent_node(state: BillingState) -> BillingState:
    """
    Core ReAct node.
    The LLM receives the conversation so far (including any tool results)
    and either:
      (a) calls one of the tools  → ToolNode will execute it next
      (b) produces a final answer → graph moves to format_response
    """
    system_prompt = (
        "You are a helpful billing support agent. "
        "Use the available tools to look up account information when needed. "
        "When calling tools, use account_id 'ACC-001' as a default if the user "
        "has not provided one. Always be concise and professional."
    )

    # Prepend system context to messages
    messages_with_system = [
        {"role": "system", "content": system_prompt},
        *state["messages"],
    ]

    response = llm_with_tools.invoke(messages_with_system)
    return {"messages": [response]}


def format_response_node(state: BillingState) -> BillingState:
    """
    Extracts the last AI message (the final answer after all tool calls)
    and stores it as final_response for A2AResponse wrapping.
    """
    # Walk backwards to find the last non-tool-call AI message
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and msg.content:
            final = msg.content
            break
    else:
        final = "I was unable to retrieve billing information at this time."

    return {**state, "final_response": final}


# ══════════════════════════════════════════════════════════════════════════════
# BUILD GRAPH
# ══════════════════════════════════════════════════════════════════════════════

def build_billing_graph() -> CompiledStateGraph:
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
    graph = StateGraph(BillingState)

    # Register nodes
    graph.add_node("agent",           agent_node)
    graph.add_node("tools",           ToolNode(TOOLS))
    graph.add_node("format_response", format_response_node)

    # Entry
    graph.set_entry_point("agent")

    # Conditional: did LLM call a tool or produce a final answer?
    graph.add_conditional_edges(
        "agent",
        tools_condition,          # built-in: checks for tool_calls in last message
        {
            "tools": "tools",     # LLM wants to call a tool
            END:     "format_response",  # LLM produced final answer
        },
    )

    # After tool executes, loop back to agent so LLM can reason over the result
    graph.add_edge("tools",           "agent")
    graph.add_edge("format_response", END)

    return graph.compile()


# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI — A2A endpoint
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Billing Agent", version="1.0")
billing_graph: CompiledStateGraph = build_billing_graph()


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    """
    A2A entry point — called by the Intent Detector orchestrator.
    Receives an A2ARequest, runs the billing ReAct graph,
    returns an A2AResponse.
    """
    initial_state: BillingState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    result = await billing_graph.ainvoke(initial_state)

    return A2AResponse(
        request_id=req.request_id,
        source_agent=AgentType.BILLING,
        status="success",
        result=result["final_response"],
        metadata={"tools_available": [t.name for t in TOOLS]},
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "billing"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "billing_agent.main:app",
        host="0.0.0.0",
        port=BILLING_AGENT_PORT,
        reload=True,
    )