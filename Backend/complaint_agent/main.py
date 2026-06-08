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
from shared.config import COMPLAINT_AGENT_PORT
from shared.llm import get_vertex_llm


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@tool
def get_complaint_history(customer_id: str) -> list[dict]:
    """
    Retrieve the past complaint tickets submitted by a customer.
    Use this when the user references a previous complaint, asks about
    the status of an existing issue, or wants to see their complaint history.
    """
    # Simulated DB response
    return [
        {
            "ticket_id":   "TKT-101",
            "date":        "2024-06-10",
            "subject":     "Wrong charge on invoice",
            "status":      "Resolved",
            "resolution":  "Credit of $20 applied to account",
        },
        {
            "ticket_id":   "TKT-087",
            "date":        "2024-04-22",
            "subject":     "Service outage not compensated",
            "status":      "Closed",
            "resolution":  "1-month service credit issued",
        },
    ]


@tool
def get_ticket_status(ticket_id: str) -> dict:
    """
    Retrieve the current status and details of a specific complaint ticket.
    Use this when the user provides a ticket ID and wants an update,
    or when following up on a specific issue.
    """
    # Simulated DB response
    statuses = {
        "TKT-101": {
            "ticket_id":  "TKT-101",
            "status":     "Resolved",
            "assigned_to": "Agent Sarah",
            "last_update": "2024-06-12",
            "notes":       "Customer confirmed resolution on 2024-06-12",
        },
        "TKT-087": {
            "ticket_id":  "TKT-087",
            "status":     "Closed",
            "assigned_to": "Agent Mike",
            "last_update": "2024-04-30",
            "notes":       "Service credit applied, case closed",
        },
    }
    return statuses.get(
        ticket_id,
        {"ticket_id": ticket_id, "status": "Not Found", "notes": "No ticket with this ID exists"},
    )


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
    # In production this could be another LLM call or a classifier model.
    # Here we use simple keyword matching as a simulation.
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


# ══════════════════════════════════════════════════════════════════════════════
# LANGGRAPH STATE
# ══════════════════════════════════════════════════════════════════════════════

class ComplaintState(TypedDict):
    request_id:     str
    user_message:   str
    messages:       Annotated[list[BaseMessage], operator.add]
    final_response: str


# ══════════════════════════════════════════════════════════════════════════════
# LLM — bind all tools
# ══════════════════════════════════════════════════════════════════════════════

TOOLS = [get_complaint_history, get_ticket_status, categorize_complaint]

llm = get_vertex_llm(temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def agent_node(state: ComplaintState) -> ComplaintState:
    """
    Core ReAct node.
    LLM decides whether to call a tool or give a final response.
    Typical flow for a new complaint:
      1. Calls categorize_complaint to understand the issue type
      2. Optionally calls get_complaint_history to check past tickets
      3. Produces a final empathetic and actionable response
    """
    system_prompt = (
        "You are a compassionate complaint resolution agent. "
        "Your goal is to understand the customer's issue, acknowledge their frustration, "
        "and provide a clear next step or resolution. "
        "Use the available tools to look up complaint history and categorize issues. "
        "Use customer_id 'CUST-001' as default if not provided by the user. "
        "Always be empathetic, professional, and solution-focused."
    )

    messages_with_system = [
        {"role": "system", "content": system_prompt},
        *state["messages"],
    ]

    response = llm_with_tools.invoke(messages_with_system)
    return {"messages": [response]}


def format_response_node(state: ComplaintState) -> ComplaintState:
    """
    Extracts the final AI answer after the ReAct loop completes.
    """
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and msg.content:
            final = msg.content
            break
    else:
        final = "I was unable to process your complaint at this time. Please try again."

    return {**state, "final_response": final}


# ══════════════════════════════════════════════════════════════════════════════
# BUILD GRAPH
# ══════════════════════════════════════════════════════════════════════════════

def build_complaint_graph() -> CompiledStateGraph:
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
    graph = StateGraph(ComplaintState)

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

app = FastAPI(title="Complaint Agent", version="1.0")
complaint_graph: CompiledStateGraph = build_complaint_graph()


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    """
    A2A entry point — called by the Intent Detector orchestrator.
    """
    initial_state: ComplaintState = {
        "request_id":     req.request_id,
        "user_message":   req.user_message,
        "messages":       [HumanMessage(content=req.user_message)],
        "final_response": "",
    }

    result = await complaint_graph.ainvoke(initial_state)

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
    import uvicorn

    uvicorn.run(
        "complaint_agent.main:app",
        host="0.0.0.0",
        port=COMPLAINT_AGENT_PORT,
        reload=True,
    )