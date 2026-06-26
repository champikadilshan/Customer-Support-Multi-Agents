import uuid
import json
import httpx
import sys
import os
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain.agents import create_agent
from langchain_core.tools import tool as lc_tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from typing import AsyncIterator, Optional

from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import AGENT_URLS, INTENT_DETECTOR_PORT
from shared.llm import get_vertex_llm
from shared.session_store import session_store
from shared.trace_emitter import trace_emitter
from shared.agent_runner import stream_agent_events

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

llm           = get_vertex_llm(temperature=0, role="orchestrator")
_checkpointer = InMemorySaver()


ORCHESTRATOR_PROMPT = """You are the orchestration agent for a telecommunications customer support system.
You coordinate three specialist agents to resolve customer requests:

  - dispatch_billing_agent   : handles invoices, charges, account balance, payment methods
  - dispatch_complaint_agent : handles complaints, ticket creation, ticket status, refunds
  - dispatch_sales_agent     : handles product info, plans, pricing, promotions, upgrades

─── ROUTING RULES ───────────────────────────────────────────────────────────────

RULE 1 — SINGLE DOMAIN: dispatch to exactly one agent.
  Examples: "what are your fiber plans", "show my balance", "raise a complaint"

RULE 2 — PARALLEL DISPATCH: dispatch to multiple agents simultaneously when the
  requests are fully independent — neither agent needs the other's result.
  Examples:
    "What plans do you have AND check my complaint status"
      → dispatch_sales_agent + dispatch_complaint_agent in parallel
    "Show my balance AND tell me about bundle deals"
      → dispatch_billing_agent + dispatch_sales_agent in parallel
    "I want to upgrade AND I have an unresolved complaint"
      → dispatch_sales_agent + dispatch_complaint_agent in parallel

RULE 3 — A2A HANDOFF (dispatch billing only, NOT complaint):
  When the user asks about a billing issue that is related to a complaint, or asks
  you to cross-reference their bill with their complaint history, dispatch ONLY to
  billing. The billing agent has direct A2A access to the complaint agent and will
  call it internally when it needs to. Do NOT also dispatch to complaint separately
  — that creates duplicate calls.
  Examples:
    "Check my bill and see if I already raised a ticket about the overcharge"
      → dispatch_billing_agent ONLY (billing calls complaint internally)
    "I was charged twice and I have an open ticket about it, what's happening?"
      → dispatch_billing_agent ONLY
    "Cross-reference my account ACC-001 with my complaint history"
      → dispatch_billing_agent ONLY

RULE 4 — NEVER DISPATCH TO COMPLAINT when billing is already handling a related issue.
  The complaint lookup will happen automatically via A2A from the billing agent.

RULE 5 — SIMPLE MESSAGES: if the user sends a greeting, a thank you, or a question
  you can answer from conversation history, respond directly without dispatching.

─── GENERAL RULES ───────────────────────────────────────────────────────────────

- NEVER fabricate information. Only use what the agents return.
- Pass the full conversation context in every dispatch so agents have history.
- If an agent returns an error, report it honestly and suggest the user try again.
- Keep responses conversational and focused on what the user actually asked.
- Do NOT explain that you are coordinating agents — present one unified experience.
- Use the customer's name and account ID if they provided them."""


class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None


class SessionResetRequest(BaseModel):
    session_id: str


def _make_dispatch_tool(agent_type: AgentType, tool_name: str, description: str):
    agent_url  = AGENT_URLS[agent_type]
    stream_url = agent_url.replace("/process", "/process/stream")

    @lc_tool(tool_name, description=description)
    def _dispatch(task: str,session_id: str = "",conversation_history: str = "[]",) -> str:
        try:
            history = json.loads(conversation_history)

        except (json.JSONDecodeError, TypeError):
            history = []

        request_id = str(uuid.uuid4())

        req = A2ARequest(
            request_id=request_id,
            source_agent=AgentType.INTENT_DETECTOR,
            target_agent=agent_type,
            user_message=task,
            context={"session_id": session_id},
            conversation_history=history,
        )

        trace_emitter.emit(
            session_id, "agent_handoff",
            from_agent="orchestrator",
            to_agent=agent_type.value, reason=task[:120],
        )

        collected: list[str] = []
        hitl_data: dict      = {}
        current_event: str   = ""

        try:
            with httpx.stream("POST", stream_url, json=req.model_dump(), timeout=60.0) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if raw_line.startswith("event:"):
                        current_event = raw_line[6:].strip()
                        continue

                    if not raw_line.startswith("data:"):
                        if raw_line == "":
                            current_event = ""  # blank line resets event type
                        continue

                    try:
                        payload = json.loads(raw_line[5:].strip())
                    except json.JSONDecodeError:
                        continue

                    if current_event == "hitl_request":
                        hitl_data = payload
                        break

                    if payload.get("text"):
                        collected.append(payload["text"])

        except Exception as exc:
            return f"[{agent_type.value} agent error: {exc}]"

        if hitl_data:
            if session_id:
                full_payload = {
                    "hitl_pending":   True,
                    "request_id":     request_id,
                    "question":       hitl_data.get("question", ""),
                    "ticket_preview": hitl_data.get("ticket_preview", {}),
                    "options":        hitl_data.get("options", ["Yes", "No"]),
                }

                session_store.set_metadata(session_id, "hitl_pending_request_id", request_id)
                session_store.set_metadata(session_id, "hitl_agent_url", agent_url.rstrip("/"))
                session_store.set_metadata(session_id, "hitl_pending_data", full_payload)

            return json.dumps(full_payload)

        return "".join(collected) or f"[{agent_type.value} agent returned no response]"

    return _dispatch


dispatch_billing_agent = _make_dispatch_tool(
    AgentType.BILLING,
    "dispatch_billing_agent",
    (
        "Dispatch to the billing specialist agent. "
        "Use for: account balance, invoice history, payment methods, overcharge checks. "
        "Include account_id if the user provided one. "
        "Pass session_id and conversation_history for context."
    ),
)


dispatch_complaint_agent = _make_dispatch_tool(
    AgentType.COMPLAINT,
    "dispatch_complaint_agent",
    (
        "Dispatch to the complaint specialist agent. "
        "Use for: raising complaint tickets, checking ticket status, complaint history, "
        "refund requests, service issues. "
        "Include customer_id if the user provided one. "
        "Pass session_id and conversation_history for context."
    ),
)


dispatch_sales_agent = _make_dispatch_tool(
    AgentType.SALES,
    "dispatch_sales_agent",
    (
        "Dispatch to the sales specialist agent. "
        "Use for: product information, plan pricing, promotions, upgrades. "
        "Pass session_id and conversation_history for context."
    ),
)

DISPATCH_TOOLS = [dispatch_billing_agent, dispatch_complaint_agent, dispatch_sales_agent]


def _build_orchestrator(session_id: str, history_json: str):
    enriched_tools = []

    for t in DISPATCH_TOOLS:
        @lc_tool(t.name, description=t.description)
        def _enriched(task: str, _t=t) -> str:
            return _t.invoke({
                "task":                 task,
                "session_id":           session_id,
                "conversation_history": history_json,
            })
        enriched_tools.append(_enriched)

    return create_agent(
        llm,
        tools=enriched_tools,
        system_prompt=ORCHESTRATOR_PROMPT,
        checkpointer=_checkpointer,
        name="orchestrator",
    )


async def stream_from_orchestrator(user_message: str,session_id: Optional[str],) -> AsyncIterator[str]:
    sess = session_store.get_or_create(session_id)
    sid  = sess.session_id

    session_store.append_messages(sid, [{"type": "human", "content": user_message}])

    session_store.set_metadata(sid, "hitl_pending_data", None)
    session_store.set_metadata(sid, "hitl_pending_request_id", None)

    yield f"event: session\ndata: {json.dumps({'session_id': sid})}\n\n"

    history      = session_store.get_messages(sid)
    history_json = json.dumps(history)

    messages = []

    for d in history:
        t = d.get("type", "")

        if t == "human":
            messages.append({"role": "user",      "content": d.get("content", "")})
        elif t == "ai":
            messages.append({"role": "assistant", "content": d.get("content", "")})

    if not messages or messages[-1]["content"] != user_message:
        messages.append({"role": "user", "content": user_message})

    agent = _build_orchestrator(sid, history_json)

    trace_emitter.emit(sid, "orchestrator_dispatch", user_message=user_message[:120])

    collected_tokens: list[str] = []

    async for raw in stream_agent_events(
        agent=agent,
        messages=messages,
        agent_name="orchestrator",
        session_id=sid,
        is_internal=False,
    ):
        is_hitl = False

        for line in raw.splitlines():
            line = line.strip()

            if line.startswith("event:") and "hitl_request" in line:
                is_hitl = True
                break

            if not line.startswith("data:"):
                continue

            try:
                payload = json.loads(line[5:].strip())
                if payload.get("text"):
                    # Guard: never forward hitl_pending JSON as chat text
                    text = payload["text"]
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict) and parsed.get("hitl_pending"):
                            rid = session_store.get_metadata(sid, "hitl_pending_request_id")
                            ai_text = "".join(collected_tokens)

                            if ai_text:
                                session_store.append_messages(sid, [{"type": "ai", "content": ai_text}])

                            yield f"event: hitl_request\ndata: {json.dumps({**parsed, 'request_id': rid})}\n\n"

                            return
                    except (json.JSONDecodeError, TypeError):
                        pass

                    collected_tokens.append(text)
            except json.JSONDecodeError:
                pass

        if is_hitl:
            rid = session_store.get_metadata(sid, "hitl_pending_request_id")
            hitl_meta = session_store.get_metadata(sid, "hitl_agent_url")
            pending = session_store.get_metadata(sid, "hitl_pending_data") or {}

            ai_text = "".join(collected_tokens)

            if ai_text:
                session_store.append_messages(sid, [{"type": "ai", "content": ai_text}])

            yield f"event: hitl_request\ndata: {json.dumps({**pending, 'request_id': rid})}\n\n"

            return

        yield raw

    ai_text = "".join(collected_tokens)
    if ai_text:
        session_store.append_messages(sid, [{"type": "ai", "content": ai_text}])


app = FastAPI(title="Orchestrator", version="5.0")


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_from_orchestrator(payload.message, payload.session_id),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/chat")
async def chat(payload: ChatRequest) -> dict:
    sess = session_store.get_or_create(payload.session_id)
    sid  = sess.session_id

    session_store.append_messages(sid, [{"type": "human", "content": payload.message}])

    collected_tokens: list[str] = []
    hitl_data:        dict      = {}

    history      = session_store.get_messages(sid)
    history_json = json.dumps(history)

    messages = []

    for d in history:
        t = d.get("type", "")
        if t == "human":
            messages.append({"role": "user",      "content": d.get("content", "")})
        elif t == "ai":
            messages.append({"role": "assistant", "content": d.get("content", "")})

    if not messages or messages[-1]["content"] != payload.message:
        messages.append({"role": "user", "content": payload.message})

    agent = _build_orchestrator(sid, history_json)

    async for raw in stream_agent_events(
        agent=agent,
        messages=messages,
        agent_name="orchestrator",
        session_id=sid,
        is_internal=False,
    ):
        for line in raw.splitlines():
            line = line.strip()

            if not line.startswith("data:"):
                continue

            try:
                p = json.loads(line[5:].strip())
                if p.get("text"):
                    # Never store hitl_pending JSON as chat text
                    text = p["text"]
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict) and parsed.get("hitl_pending"):
                            continue   # skip — will be returned as hitl fields below
                    except (json.JSONDecodeError, TypeError):
                        pass
                    collected_tokens.append(text)

            except json.JSONDecodeError:
                pass

    final_text = "".join(collected_tokens)
    if final_text:
        session_store.append_messages(sid, [{"type": "ai", "content": final_text}])

    result: dict = {"session_id": sid, "response": final_text}

    hitl_data = session_store.get_metadata(sid, "hitl_pending_data") or {}

    if hitl_data:
        rid = session_store.get_metadata(sid, "hitl_pending_request_id")
        result.update({
            "hitl_pending":   True,
            "request_id":     rid,
            "ticket_preview": hitl_data.get("ticket_preview", {}),
            "hitl_question":  hitl_data.get("question", ""),
            "hitl_options":   hitl_data.get("options", ["Yes", "No"]),
        })

    return result


@app.post("/session/reset")
def session_reset(body: SessionResetRequest) -> dict:
    ok = session_store.reset(body.session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found.")
    return {"status": "reset", "session_id": body.session_id}


@app.delete("/session/{session_id}")
def session_delete(session_id: str) -> dict:
    ok = session_store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"status": "deleted", "session_id": session_id}


@app.get("/session/{session_id}")
def session_info(session_id: str) -> dict:
    info = session_store.session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return info


@app.post("/internal/trace")
async def internal_trace(event: dict) -> dict:
    trace_emitter.receive(event)
    return {"status": "ok"}


@app.get("/chat/trace/{session_id}")
async def chat_trace(session_id: str) -> StreamingResponse:

    if session_store.get(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    return StreamingResponse(
        trace_emitter.stream(session_id, timeout_s=300),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/chat/trace/{session_id}/replay")
def chat_trace_replay(session_id: str) -> dict:
    if session_store.get(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"session_id": session_id, "events": trace_emitter.get_events(session_id)}


@app.get("/health")
def health():
    return {
        "status":          "ok",
        "agent":           "orchestrator",
        "active_sessions": len(session_store.all_session_ids()),
    }


if __name__ == "__main__":
    uvicorn.run(
        "intent_detector.main:app",
        host="0.0.0.0",
        port=INTENT_DETECTOR_PORT,
        reload=True,
    )