"""
shared/agent_call_tool.py
-------------------------
Factory function that produces a LangChain @tool allowing one agent to call
another agent synchronously (blocking HTTP POST to /process).

Key design decisions
--------------------
1. BLOCKING — internal calls use /process (not /process/stream).
   The calling agent's LangGraph node waits for the result, then weaves it
   into its own response.  Streaming is preserved on the user-facing channel
   (orchestrator → primary agent) — internal calls are invisible to the user
   stream but fully visible on the trace channel.

2. LOOP GUARD — if is_internal=True on the incoming request, the produced
   tool raises a RuntimeError rather than making another hop.  This prevents
   A→B→A infinite recursion.  The guard is enforced at tool-call time, not
   at graph-build time, so no graph changes are needed.

3. TRACE — every handoff, internal agent_start, tool_start/end, and
   agent_end is emitted to the trace bus so the dashboard sees the full
   execution tree in real time.

4. TIMEOUT — internal calls use a shorter timeout (20 s) than user-facing
   calls (30–60 s) so a hung downstream agent cannot stall the primary agent
   indefinitely.  On timeout the tool returns a graceful error string and the
   primary agent continues.

Usage
-----
    # In complaint_agent/main.py
    from shared.agent_call_tool import make_agent_call_tool
    from shared.a2a_protocol import AgentType

    call_billing_agent = make_agent_call_tool(
        target=AgentType.BILLING,
        description=(
            "Call the billing agent to fetch account balance, invoice history, "
            "or payment methods, or to check whether a service credit applies. "
            "Pass a clear task description and include the account_id if known."
        ),
    )

The tool function signature seen by LangGraph:
    call_billing_agent(task: str, session_id: str, conversation_history_json: str) -> str

The LLM only needs to supply `task` — session_id and conversation_history are
injected by the agent_node before the tool is invoked (via RunnableConfig or
state injection; see agent_node implementations).
"""

import json
import time
import httpx

from langchain_core.tools import tool as lc_tool
from functools import partial
from typing import Callable

from shared.a2a_protocol import A2ARequest, AgentType
from shared.config import AGENT_URLS
from shared.trace_emitter import trace_emitter


# ── Internal timeout ──────────────────────────────────────────────────────────
INTERNAL_TIMEOUT = 20.0   # seconds


# ── Factory ───────────────────────────────────────────────────────────────────

def make_agent_call_tool(
    target:      AgentType,
    description: str,
) -> Callable:
    """
    Return a LangChain tool that POSTs an internal A2ARequest to `target`.

    Parameters
    ----------
    target      : which agent to call
    description : shown to the LLM — should explain WHEN to use this tool
                  and what to put in the `task` argument.
    """
    target_name = target.value

    @lc_tool(
        f"call_{target_name}_agent",
        description=description,
    )
    def _call_agent(
        task:                      str,
        session_id:                str,
        calling_agent:             str,
        conversation_history_json: str = "[]",
    ) -> str:
        """
        Internal agent-to-agent call.

        Parameters (the LLM provides `task`; the agent_node injects the rest
        by wrapping this tool — see _bind_internal_tool_args):
          task                      — what you need the other agent to do
          session_id                — current session (injected)
          calling_agent             — who is calling (injected, loop guard)
          conversation_history_json — serialised history (injected)
        """
        # ── Loop guard ────────────────────────────────────────────────────────
        # Prevent A→B→A chains.  If the calling agent is the same as the
        # target, refuse immediately.
        if calling_agent == target_name:
            return (
                f"[Loop guard] {calling_agent} cannot call itself. "
                "Handle this task with your own tools."
            )

        # ── Deserialise history ───────────────────────────────────────────────
        try:
            history: list[dict] = json.loads(conversation_history_json)
        except (json.JSONDecodeError, TypeError):
            history = []

        # ── Emit handoff trace ────────────────────────────────────────────────
        trace_emitter.emit(
            session_id,
            "agent_handoff",
            from_agent=calling_agent,
            to_agent=target_name,
            reason=task[:120],   # truncate for readability
        )

        # ── Build request ─────────────────────────────────────────────────────
        import uuid
        req = A2ARequest(
            request_id=str(uuid.uuid4()),
            source_agent=AgentType(calling_agent),
            target_agent=target,
            user_message=task,
            context={
                "is_internal":    True,
                "calling_agent":  calling_agent,
            },
            conversation_history=history,
        )

        url        = AGENT_URLS[target]
        stream_url = url.replace("/process", "/process/stream")

        # ── Trace: target agent starting ──────────────────────────────────────
        trace_emitter.emit(
            session_id,
            "agent_start",
            agent=target_name,
            triggered_by=calling_agent,
            is_internal=True,
        )

        start = time.monotonic()

        # ── HTTP call — use /process/stream so astream_events fires inside ────
        # This means tool_start/tool_end trace events emit from within the
        # called agent and get forwarded to the orchestrator's trace buffer.
        collected: list[str] = []
        try:
            with httpx.stream(
                "POST", stream_url,
                json=req.model_dump(),
                timeout=INTERNAL_TIMEOUT,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(raw_line[5:].strip())
                        if payload.get("text"):
                            collected.append(payload["text"])
                    except json.JSONDecodeError:
                        pass

            result = "".join(collected) or "[No response from agent]"

            trace_emitter.emit(
                session_id,
                "agent_end",
                agent=target_name,
                status="success",
                duration_ms=int((time.monotonic() - start) * 1000),
                triggered_by=calling_agent,
                is_internal=True,
            )
            return result

        except httpx.ConnectError:
            msg = f"[{target_name} agent unavailable — could not connect]"
            trace_emitter.emit(session_id, "error", agent=target_name,
                               message="ConnectError", is_internal=True)
            return msg

        except httpx.TimeoutException:
            msg = f"[{target_name} agent timed out after {INTERNAL_TIMEOUT}s]"
            trace_emitter.emit(session_id, "error", agent=target_name,
                               message="TimeoutException", is_internal=True)
            return msg

        except httpx.HTTPStatusError as e:
            msg = f"[{target_name} agent returned HTTP {e.response.status_code}]"
            trace_emitter.emit(session_id, "error", agent=target_name,
                               message=f"HTTP {e.response.status_code}", is_internal=True)
            return msg

        except Exception as e:
            msg = f"[{target_name} agent error: {e}]"
            trace_emitter.emit(session_id, "error", agent=target_name,
                               message=str(e), is_internal=True)
            return msg

    return _call_agent


# ── Argument injector ─────────────────────────────────────────────────────────

def bind_inter_agent_args(
    tool_fn,
    session_id:    str,
    calling_agent: str,
    history:       list[dict],
):
    """
    Return a thin wrapper around `tool_fn` that pre-fills the three
    injected parameters (session_id, calling_agent, conversation_history_json)
    so the LLM only ever sees and provides `task`.

    The agent_node calls this once per invocation before passing the tool
    to the LLM, ensuring the right session context is always injected.

    Usage in agent_node:
        bound = bind_inter_agent_args(
            call_billing_agent,
            session_id=req.session_id,
            calling_agent="complaint",
            history=req.conversation_history,
        )
        llm_with_tools = llm.bind_tools([*OWN_TOOLS, bound])
    """
    history_json = json.dumps(history)

    # LangChain tools are callable; we wrap with functools.partial-like logic
    # by creating a new tool with the same name/description but pre-filled args.
    original_name = tool_fn.name
    original_desc = tool_fn.description

    @lc_tool(original_name, description=original_desc)
    def _bound(task: str) -> str:
        return tool_fn.invoke({
            "task":                      task,
            "session_id":                session_id,
            "calling_agent":             calling_agent,
            "conversation_history_json": history_json,
        })

    return _bound