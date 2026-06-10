import type { AgentNodeId } from "@/lib/agent-graph"

export const TOOL_LABELS: Record<string, string> = {
  get_account_balance: "Account Balance",
  get_invoice_history: "Invoice History",
  get_payment_methods: "Payment Methods",
  get_complaint_history: "Complaint History",
  get_ticket_status: "Ticket Status",
  categorize_complaint: "Categorize Complaint",
  stage_ticket_creation: "Stage Ticket",
  create_ticket: "Create Ticket",
  get_product_catalog: "Product Catalog",
  get_active_promotions: "Promotions",
  check_product_availability: "Availability",
  call_billing_agent: "Call Billing Agent",
  call_complaint_agent: "Call Complaint Agent",
  call_sales_agent: "Call Sales Agent",
}

/** Tools each agent can invoke (matches backend LangGraph tool lists). */
export const AGENT_TOOL_IDS: Partial<Record<AgentNodeId, string[]>> = {
  billing: [
    "get_account_balance",
    "get_invoice_history",
    "get_payment_methods",
    "call_complaint_agent",
  ],
  complaint: [
    "categorize_complaint",
    "get_complaint_history",
    "get_ticket_status",
    "stage_ticket_creation",
    "create_ticket",
    "call_billing_agent",
    "call_sales_agent",
  ],
  sales: [
    "get_product_catalog",
    "get_active_promotions",
    "check_product_availability",
    "call_billing_agent",
    "call_complaint_agent",
  ],
}

/** Which infra nodes light up when a tool runs (from backend architecture). */
export const TOOL_INFRA_ACTIVATION: Record<
  string,
  { nodes: AgentNodeId[]; edges: [AgentNodeId, AgentNodeId][] }
> = {
  get_account_balance: {
    nodes: ["billing_db"],
    edges: [["billing", "billing_db"]],
  },
  get_invoice_history: {
    nodes: ["billing_db"],
    edges: [["billing", "billing_db"]],
  },
  get_payment_methods: {
    nodes: ["billing_db"],
    edges: [["billing", "billing_db"]],
  },
  get_product_catalog: {
    nodes: ["sales_mcp", "product_db"],
    edges: [
      ["sales", "sales_mcp"],
      ["sales_mcp", "product_db"],
    ],
  },
  get_active_promotions: {
    nodes: ["sales_mcp", "product_db"],
    edges: [
      ["sales", "sales_mcp"],
      ["sales_mcp", "product_db"],
    ],
  },
  check_product_availability: {
    nodes: ["sales_mcp", "product_db"],
    edges: [
      ["sales", "sales_mcp"],
      ["sales_mcp", "product_db"],
    ],
  },
  get_complaint_history: {
    nodes: ["ticket_api", "ticket_db"],
    edges: [
      ["complaint", "ticket_api"],
      ["ticket_api", "ticket_db"],
    ],
  },
  get_ticket_status: {
    nodes: ["ticket_api", "ticket_db"],
    edges: [
      ["complaint", "ticket_api"],
      ["ticket_api", "ticket_db"],
    ],
  },
  stage_ticket_creation: {
    nodes: ["hitl"],
    edges: [["complaint", "hitl"]],
  },
  create_ticket: {
    nodes: ["ticket_api", "ticket_db"],
    edges: [
      ["complaint", "ticket_api"],
      ["ticket_api", "ticket_db"],
    ],
  },
}

export function formatToolLabel(toolId: string) {
  return (
    TOOL_LABELS[toolId] ??
    toolId.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase())
  )
}

export function isInterAgentTool(toolId: string) {
  return toolId.startsWith("call_") && toolId.endsWith("_agent")
}

export const INTER_AGENT_TOOL_TARGETS: Record<string, AgentNodeId> = {
  call_billing_agent: "billing",
  call_complaint_agent: "complaint",
  call_sales_agent: "sales",
}
