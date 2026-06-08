import os
from pathlib import Path

from dotenv import load_dotenv

from shared.a2a_protocol import AgentType

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

AGENT_HOST = os.getenv("AGENT_HOST", "localhost")

TICKET_SERVICE_PORT  = int(os.getenv("TICKET_SERVICE_PORT",  "8000"))
INTENT_DETECTOR_PORT = int(os.getenv("INTENT_DETECTOR_PORT", "8001"))
BILLING_AGENT_PORT   = int(os.getenv("BILLING_AGENT_PORT",   "8002"))
COMPLAINT_AGENT_PORT = int(os.getenv("COMPLAINT_AGENT_PORT", "8003"))
SALES_AGENT_PORT     = int(os.getenv("SALES_AGENT_PORT",     "8004"))
SALES_MCP_PORT       = int(os.getenv("SALES_MCP_PORT",       "8005"))

# Neo4j AuraDB — credentials from .env
# Get these from your AuraDB instance dashboard at neo4j.io/aura
NEO4J_URI      = os.getenv("NEO4J_URI", "neo4j+s://xxxx.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


def agent_process_url(port: int) -> str:
    return f"http://{AGENT_HOST}:{port}/process"


AGENT_URLS: dict[AgentType, str] = {
    AgentType.BILLING:   agent_process_url(BILLING_AGENT_PORT),
    AgentType.COMPLAINT: agent_process_url(COMPLAINT_AGENT_PORT),
    AgentType.SALES:     agent_process_url(SALES_AGENT_PORT),
}