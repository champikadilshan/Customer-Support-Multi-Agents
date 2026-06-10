import uuid
import json
import httpx
import asyncio
import sys
import os
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from pydantic import BaseModel
from typing import AsyncIterator, Optional
from shared.a2a_protocol import A2ARequest, A2AResponse, AgentType
from shared.config import AGENT_URLS, INTENT_DETECTOR_PORT
from shared.llm import get_vertex_llm
from shared.session_store import session_store
from shared.message_utils import messages_to_dicts, dicts_to_messages
from shared.trace_emitter import trace_emitter
from shared.agent_loop import run_agent_loop, _sse, _extract_text

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

llm = get_vertex_llm(temperature=0)


class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None

class SessionResetRequest(BaseModel):
    session_id: str


ORCHESTRATOR_PROMPT = """You are the orchestration agent for a telecommunications customer support system.
You coordinate three specialist agents to resolve customer requests:

  - dispatch_billing_agent   : handles invoices, charges, account balance, payment methods
  - dispatch_complaint_agent : handles complaints, ticket creation, ticket status, refunds
  - dispatch_sales_agent     : handles product info, plans, pricing, promotions, upgrades

Your workflow for every user message:
1. Read the user message and conversation history carefully.
2. Decide which specialist agent(s) can best handle this request.
3. Dispatch to the relevant agent(s) using the dispatch tools.
   - If the request spans multiple domains (e.g. "check my bill AND I want to complain"),
     dispatch to billing first, then complaint with the billing result as context.
   - If the request is purely one domain, dispatch to that agent only.
4. Synthesise the agent response(s) into a single coherent reply to the user.

Rules:
- NEVER fabricate information. Only use what the agents return.
- Pass the full conversation context in each dispatch so agents have history.
- If an agent returns an error, report it honestly and suggest the user try again.
- Keep responses conversational and focused on what the user actually asked.
- Do NOT explain that you are coordinating agents — present one unified experience.
- Use the customer's name if they provided it. Use account_id / customer_id if mentioned."""


def _make_dispatch_tool( agent_type: AgentType, tool_name:  str,description: str,):
    agent_url = AGENT_URLS[agent_type]
    stream_url = agent_url.replace("/process", "/process/stream")

    @lc_tool(tool_name, description=description)
    def _dispatch(task:str,session_id:str = "",conversation_history: str = "[]", ) -> str:
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

        trace_emitter.emit(session_id, "agent_handoff", from_agent="orchestrator",to_agent=agent_type.value,reason=task[:120])

        collected: list[str] = []
        hitl_data: dict      = {}

        try:
            import httpx as _httpx
            with _httpx.stream( "POST", stream_url, json=req.model_dump(), timeout=60.0, ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(raw_line[5:].strip())
                        if payload.get("text"):
                            collected.append(payload["text"])
                        if payload.get("ticket_preview"):
                            hitl_data = payload
                    except json.JSONDecodeError:
                        pass

        except Exception as exc:
            return f"[{agent_type.value} agent error: {exc}]"

        if hitl_data:
            if session_id:
                session_store.set_metadata(session_id, "hitl_pending_request_id", request_id)
                session_store.set_metadata(session_id, "hitl_agent_port", str(agent_url).rstrip("/"))

            return json.dumps({
                "hitl_pending":   True,
                "request_id":     request_id,
                "question":       hitl_data.get("question", ""),
                "ticket_preview": hitl_data.get("ticket_preview", {}),
                "options":        hitl_data.get("options", ["Yes", "No"]),
            })

        return "".join(collected) or f"[{agent_type.value} agent returned no response]"

    return _dispatch


dispatch_billing_agent = _make_dispatch_tool(
    AgentType.BILLING,
    "dispatch_billing_agent",
    (
        "Dispatch to the billing specialist agent. "
        "Use for: account balance, invoice history, payment methods, overcharge checks, "
        "billing anomalies. "
        "Pass a clear task description. Include account_id if the user provided one. "
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
        "Pass a clear task description. Include customer_id if the user provided one. "
        "Pass session_id and conversation_history for context."
    ),
)

dispatch_sales_agent = _make_dispatch_tool(
    AgentType.SALES,
    "dispatch_sales_agent",
    (
        "Dispatch to the sales specialist agent. "
        "Use for: product information, plan pricing, promotions, upgrades, availability checks. "
        "Pass a clear task description. "
        "Pass session_id and conversation_history for context."
    ),
)

DISPATCH_TOOLS = [dispatch_billing_agent, dispatch_complaint_agent, dispatch_sales_agent]
TOOL_MAP       = {t.name: t for t in DISPATCH_TOOLS}


def _build_history_injection(session_id: str) -> str:
    return json.dumps(session_store.get_messages(session_id))


async def _run_orchestrator(user_message: str,session_id:   str,) -> AsyncIterator[str]:
    history = session_store.get_messages(session_id)
    history_json   = json.dumps(history)

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

    enriched_tool_map = {t.name: t for t in enriched_tools}
    llm_with_tools    = llm.bind_tools(enriched_tools)

    prior = dicts_to_messages(history)
    if not prior or not isinstance(prior[-1], HumanMessage):
        prior.append(HumanMessage(content=user_message))

    messages = [SystemMessage(content=ORCHESTRATOR_PROMPT), *prior]

    trace_emitter.emit(session_id, "orchestrator_dispatch",
                       user_message=user_message[:120])

    async for chunk in run_agent_loop(
        llm_with_tools=llm_with_tools,
        messages=messages,
        tool_map=enriched_tool_map,
        agent_name="orchestrator",
        session_id=session_id,
        is_internal=False,
    ):
        yield chunk


def _make_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_from_orchestrator(user_message: str,session_id:   Optional[str],) -> AsyncIterator[str]:
    sess = session_store.get_or_create(session_id)
    sid  = sess.session_id

    session_store.append_messages(sid, [{"type": "human", "content": user_message}])

    yield _make_sse("session", {"session_id": sid})

    collected_tokens: list[str] = []
    hitl_data:        dict      = {}

    async for raw in _run_orchestrator(user_message, sid):
        for line in raw.splitlines():
            line = line.strip()

            if not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[5:].strip())
                if payload.get("text"):
                    collected_tokens.append(payload["text"])
                if payload.get("ticket_preview"):
                    hitl_data = payload
            except json.JSONDecodeError:
                pass

        yield raw

    ai_text = "".join(collected_tokens)
    if ai_text:
        session_store.append_messages(sid, [{"type": "ai", "content": ai_text}])

    if hitl_data and not hitl_data.get("text"):
        yield _make_sse("hitl_request", hitl_data)


app = FastAPI(title="Orchestrator", version="4.0")


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

    async for raw in _run_orchestrator(payload.message, sid):
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("event:") and "hitl_request" in line:
                continue
            if not line.startswith("data:"):
                continue

            try:
                p = json.loads(line[5:].strip())
                if p.get("text"):
                    collected_tokens.append(p["text"])
                if p.get("ticket_preview") or p.get("hitl_pending"):
                    hitl_data = p
            except json.JSONDecodeError:
                pass

    final_text = "".join(collected_tokens)
    if final_text:
        session_store.append_messages(sid, [{"type": "ai", "content": final_text}])

    result = {
        "session_id": sid,
        "response":   final_text,
    }
    if hitl_data:
        rid = session_store.get_metadata(sid, "hitl_pending_request_id")
        result["hitl_pending"]   = True
        result["request_id"]     = rid
        result["ticket_preview"] = hitl_data.get("ticket_preview", {})
        result["hitl_question"]  = hitl_data.get("question", "")
        result["hitl_options"]   = hitl_data.get("options", ["Yes", "No"])

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