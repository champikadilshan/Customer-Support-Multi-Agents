import json
import time
import httpx
import uuid

from langchain_core.tools import tool as lc_tool
from functools import partial
from typing import Callable
from shared.a2a_protocol import A2ARequest, AgentType
from shared.config import AGENT_URLS
from shared.trace_emitter import trace_emitter

INTERNAL_TIMEOUT = 20.0   # seconds


def make_agent_call_tool(target: AgentType,description: str,) -> Callable:
    target_name = target.value

    @lc_tool( f"call_{target_name}_agent", description=description, )
    def _call_agent(task: str, session_id: str, calling_agent: str, conversation_history_json: str = "[]",) -> str:
        # Prevent A→B→A chains.  If the calling agent is the same as the target, refuse immediately.
        if calling_agent == target_name:
            return (
                f"[Loop guard] {calling_agent} cannot call itself. "
                "Handle this task with your own tools."
            )

        try:
            history: list[dict] = json.loads(conversation_history_json)
        except (json.JSONDecodeError, TypeError):
            history = []

        trace_emitter.emit(
            session_id,
            "agent_handoff",
            from_agent=calling_agent,
            to_agent=target_name,
            reason=task[:120],   # truncate for readability
        )

        req = A2ARequest(
            request_id=str(uuid.uuid4()),
            source_agent=AgentType(calling_agent),
            target_agent=target,
            user_message=task,
            context={"session_id": session_id},
            conversation_history=history,
            is_internal=True,
            calling_agent=calling_agent,
        )

        url        = AGENT_URLS[target]
        stream_url = url.replace("/process", "/process/stream")

        trace_emitter.emit(
            session_id,
            "agent_start",
            agent=target_name,
            triggered_by=calling_agent,
            is_internal=True,
        )

        start = time.monotonic()

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


def bind_inter_agent_args( tool_fn,session_id:str,calling_agent: str, history:list[dict],):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    history_json   = json.dumps(history)
    original_name  = tool_fn.name
    original_desc  = tool_fn.description


    class _BoundInput(BaseModel):
        task: str = Field(description="The task description to pass to the agent.")

    def _bound_fn(task: str) -> str:
        return tool_fn.invoke({
            "task":                      task,
            "session_id":                session_id,
            "calling_agent":             calling_agent,
            "conversation_history_json": history_json,
        })

    bound_tool = StructuredTool.from_function(
        func=_bound_fn,
        name=original_name,
        description=original_desc,
        args_schema=_BoundInput,
    )

    return bound_tool