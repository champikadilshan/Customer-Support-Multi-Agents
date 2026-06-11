"""
billing_agent/main.py

Tools reduced from three hardcoded query functions to two generic tools:

  get_tables        — returns full schema (table names + columns + types)
                      cached in memory after first call, schema never changes at runtime

  query_database    — LLM composes and runs any SELECT query
                      read-only enforced: INSERT / UPDATE / DELETE / DROP / ALTER / PRAGMA
                      are all rejected before execution
                      results capped at MAX_ROWS to protect context window
"""

import json
import re
import sys
import os
import uvicorn

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain.agents import create_agent
from langchain_core.tools import tool as lc_tool
from langgraph.checkpoint.memory import InMemorySaver
from typing import AsyncIterator, Optional

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import BILLING_AGENT_PORT
from shared.llm import get_vertex_llm
from shared.agent_call_tool import make_agent_call_tool, bind_inter_agent_args
from shared.agent_runner import stream_agent_events
from shared.trace_emitter import trace_emitter
from billing_agent.database import create_db_and_tables, engine

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_ROWS = 50   # max rows returned to LLM — protects context window

# Disallowed SQL statement types — checked against the first keyword of the
# stripped, uppercased query.  We block writes and schema mutations entirely.
_WRITE_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "REPLACE",
    "DROP", "ALTER", "CREATE", "TRUNCATE",
    "ATTACH", "DETACH", "PRAGMA", "VACUUM",
    "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT",
}

# ── Schema cache ──────────────────────────────────────────────────────────────
# Populated once on first get_tables call, reused for every subsequent call.
# The billing schema never changes at runtime so this is always safe.
_schema_cache: Optional[list[dict]] = None


def _is_select_only(sql: str) -> tuple[bool, str]:
    """
    Returns (True, "") if sql is a safe SELECT-only query.
    Returns (False, reason) otherwise.

    Strategy:
      1. Strip comments and leading whitespace.
      2. Extract the first word — that is the statement type.
      3. Reject if it is in the write/mutation keyword set.
      4. Additionally scan the full statement for semicolons followed by
         a write keyword — blocks stacked statements like
         "SELECT 1; DROP TABLE accountbalance".
    """
    # Strip single-line comments (-- ...) and block comments (/* ... */)
    cleaned = re.sub(r"--[^\n]*", " ", sql)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()

    if not cleaned:
        return False, "Empty query"

    first_word = cleaned.split()[0].upper()

    if first_word != "SELECT":
        return False, (
            f"Only SELECT statements are allowed. "
            f"Got: {first_word}"
        )

    # Check for stacked statements — find every token after a semicolon
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    for stmt in statements[1:]:                     # skip the first SELECT
        word = stmt.split()[0].upper() if stmt.split() else ""
        if word in _WRITE_KEYWORDS or word == "SELECT":
            # Even a second SELECT is suspicious in a stacked context — reject
            return False, (
                f"Stacked statements are not allowed. "
                f"Found '{word}' after semicolon."
            )

    return True, ""


# ── Tools ─────────────────────────────────────────────────────────────────────

@lc_tool(
    "get_tables",
    description=(
        "Return the full schema of the billing database: every table name, "
        "its columns, and their data types. "
        "Always call this FIRST before query_database if you are unsure which "
        "tables or columns exist. The result is cached — calling it multiple "
        "times in one conversation is free."
    ),
)
def get_tables() -> list[dict]:
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    schema = []
    with engine.connect() as conn:
        # Get all user-created tables (exclude SQLite internals)
        tables_result = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        )
        table_names = [row[0] for row in tables_result]

        for table_name in table_names:
            cols_result = conn.execute(
                __import__("sqlalchemy").text(f"PRAGMA table_info('{table_name}')")
            )
            columns = [
                {
                    "name":     row[1],
                    "type":     row[2],
                    "not_null": bool(row[3]),
                    "pk":       bool(row[5]),
                }
                for row in cols_result
            ]
            schema.append({
                "table":   table_name,
                "columns": columns,
            })

    _schema_cache = schema
    return schema


@lc_tool(
    "query_database",
    description=(
        "Execute a read-only SELECT query against the billing database and "
        "return the results as a list of row dicts. "
        "Rules you must follow:\n"
        "  - Only SELECT statements are allowed. Never INSERT, UPDATE, DELETE, "
        "    DROP, ALTER, or any other write/mutation statement.\n"
        "  - Always call get_tables first if you do not know the schema.\n"
        "  - Results are capped at 50 rows. If truncated is true in the "
        "    response, tell the user only partial results are shown.\n"
        "  - Column names are case-sensitive — use exact names from get_tables.\n"
        "  - SQLite syntax: use LIKE for pattern matching, strftime() for "
        "    date formatting, LIMIT for row counts."
    ),
)
def query_database(sql: str) -> dict:
    # ── Safety check ─────────────────────────────────────────────────────────
    ok, reason = _is_select_only(sql)
    if not ok:
        return {
            "error":   reason,
            "hint":    "Rewrite the query as a SELECT statement.",
            "sql":     sql,
        }

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        import sqlalchemy
        with engine.connect() as conn:
            result = conn.execute(sqlalchemy.text(sql))
            columns = list(result.keys())
            rows    = result.fetchmany(MAX_ROWS + 1)   # fetch one extra to detect truncation

        truncated = len(rows) > MAX_ROWS
        rows      = rows[:MAX_ROWS]

        return {
            "columns":   columns,
            "rows":      [dict(zip(columns, row)) for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }

    except Exception as exc:
        # Return the error as data — the LLM can self-correct and retry
        return {
            "error": str(exc),
            "hint":  "Check column names and table names using get_tables.",
            "sql":   sql,
        }


# ── Inter-agent tool ──────────────────────────────────────────────────────────

_call_complaint_agent_tool = make_agent_call_tool(
    target=AgentType.COMPLAINT,
    description=(
        "Call the complaint agent to retrieve existing ticket status or complaint history. "
        "Use this in two situations: "
        "(1) The customer directly asks about a previous complaint or ticket during a billing conversation. "
        "(2) You found a billing anomaly (unexpected charge, duplicate payment, balance spike) "
        "    AND want to check whether the customer already has an open ticket about it — "
        "    so you can give them a complete picture without asking them to contact another team. "
        "Do NOT use this to create or stage new tickets. "
        "Do NOT call this just because complaints were mentioned in the original user message — "
        "only call it when YOU need the complaint data to complete your billing response."
    ),
)

OWN_TOOLS = [get_tables, query_database]

# ── Prompts ───────────────────────────────────────────────────────────────────

USER_FACING_PROMPT = """You are a helpful and professional billing support agent for a telecommunications company.

DATABASE TOOLS:
You have two tools to access billing data:
  - get_tables: call this once to learn the schema (table names and columns).
  - query_database: write and run any SELECT query to answer the user's question.

Always call get_tables first in a new conversation before writing any query.
After the first call the schema is in your context — do not call get_tables again.

CONVERSATION BEHAVIOUR:
1. Greet the user warmly on the first message. On subsequent turns continue naturally.
2. Before querying, ensure you have the customer's account ID.
   If missing, politely ask for it. Never re-ask for information already given.
3. Use query_database to fetch data before answering billing questions.
   Write precise SQL — filter by account_id, order by date desc, limit rows sensibly.
4. When you find an anomaly (unexpected charge, balance spike vs prior invoices),
   explain it clearly and ask: "Would you like me to raise a complaint ticket about this?"
5. When the customer agrees to raise a ticket, say:
   "I've noted your complaint. I'm transferring you to our complaint team now —
   they will confirm the details and raise the ticket for you."
   Then STOP. Do NOT call any tool. The system routes the next message automatically.
6. A2A COLLABORATION — when to call call_complaint_agent:
   - The customer asks about a previous complaint or ticket during this billing conversation.
   - You found a billing anomaly AND want to check if an open ticket already exists for it,
     so you can give the customer a complete picture in one response.
   In both cases pass the customer_id and a clear task description.
   NEVER use call_complaint_agent to create tickets.
   NEVER call it just because the user mentioned complaints in their message —
   only call it when you genuinely need complaint data to complete your answer.
7. Never expose raw SQL results or JSON to the user — translate into friendly language.
8. Close warmly if the customer says goodbye."""

INTERNAL_PROMPT = """You are the billing agent responding to an internal request from another agent.
Return a concise factual answer. Do NOT greet.
Use get_tables then query_database to fetch the data.
Default to account_id 'ACC-001' if none is specified."""

# ── LLM + checkpointer ────────────────────────────────────────────────────────

llm           = get_vertex_llm(temperature=0, role="specialist")
_checkpointer = InMemorySaver()   # production: AsyncPostgresSaver

# ── Agent factory ─────────────────────────────────────────────────────────────

def _build_agent(req: A2ARequest, session_id: str):
    if req.is_internal:
        tools  = list(OWN_TOOLS)
        prompt = INTERNAL_PROMPT
    else:
        bound_complaint = bind_inter_agent_args(
            _call_complaint_agent_tool,
            session_id=session_id,
            calling_agent=AgentType.BILLING.value,
            history=req.conversation_history,
        )
        tools  = [*OWN_TOOLS, bound_complaint]
        prompt = USER_FACING_PROMPT

    return create_agent(
        llm,
        tools=tools,
        system_prompt=prompt,
        checkpointer=_checkpointer,
        name="billing",
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
                         "name": d.get("name", ""),
                         "tool_call_id": d.get("tool_call_id", "")})

    last_is_user = (
        msgs and
        msgs[-1]["role"] == "user" and
        msgs[-1]["content"] == req.user_message
    )
    if not last_is_user:
        msgs.append({"role": "user", "content": req.user_message})

    return msgs


# ── Streaming entry point ─────────────────────────────────────────────────────

async def stream_billing_agent(req: A2ARequest) -> AsyncIterator[str]:
    session_id = req.context.get("session_id", req.request_id)
    trace_emitter.emit(
        session_id, "agent_start", agent="billing",
        is_internal=req.is_internal,
        triggered_by=req.calling_agent or "orchestrator",
    )

    agent    = _build_agent(req, session_id)
    messages = _build_messages(req)

    async for chunk in stream_agent_events(
        agent=agent,
        messages=messages,
        agent_name="billing",
        session_id=session_id,
        is_internal=req.is_internal,
    ):
        yield chunk


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Billing Agent", version="5.0")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


@app.post("/process/stream")
async def process_stream(req: A2ARequest) -> StreamingResponse:
    return StreamingResponse(
        stream_billing_agent(req),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/process", response_model=A2AResponse)
async def process(req: A2ARequest) -> A2AResponse:
    session_id = req.context.get("session_id", req.request_id)
    final_text = ""

    async for raw in stream_billing_agent(req):
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
        source_agent=AgentType.BILLING,
        status="success",
        result=final_text or "I was unable to retrieve billing information at this time.",
        metadata={"tools_available": [t.name for t in OWN_TOOLS]},
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent": "billing"}


if __name__ == "__main__":
    uvicorn.run(
        "billing_agent.main:app",
        host="0.0.0.0",
        port=BILLING_AGENT_PORT,
        reload=True,
    )