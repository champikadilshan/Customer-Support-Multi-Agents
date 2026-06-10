"""
shared/agent_runner.py

Uses astream(stream_mode=["updates", "messages"], version="v2") —
the stable, non-experimental streaming API for create_agent graphs.

  "messages" mode → (token, metadata) tuples from LLM nodes
                    token.content_blocks contains text deltas
                    metadata["langgraph_node"] identifies the source

  "updates" mode  → state dict per step
                    used to detect tool calls arriving from the tools node

Both modes are yielded as (mode, chunk) tuples when passed as a list.
No node-name hardcoding, no isinstance checks, no seen_ids.
The framework delivers typed chunks — we just read their documented fields.
"""

import json
import asyncio
from typing import AsyncIterator, Any

from langgraph.types import Command
from shared.trace_emitter import trace_emitter


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _text_from_content_blocks(content_blocks) -> str:
    """
    Extract plain text from content_blocks.
    content_blocks is a list of dicts: [{"type": "text", "text": "..."}, ...]
    This is the documented structure of token.content_blocks in messages mode.
    """
    if not content_blocks:
        return ""
    return "".join(
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )


async def stream_agent_events(
    *,
    agent,
    messages,            # list[dict] for first call, Command for resume
    agent_name: str,
    session_id: str,
    is_internal: bool = False,
) -> AsyncIterator[str]:
    """
    Streams SSE from a create_agent graph.

    `messages` is either:
      - list[dict]  e.g. [{"role": "user", "content": "..."}]  — first call
      - Command     e.g. Command(resume=None)                   — HITL resume

    Uses stream_mode=["updates", "messages"].
    Each iteration yields (mode, chunk):
      - mode="messages": (token, metadata) — text tokens from LLM
      - mode="updates":  state dict — step completions, tool calls

    SSE events emitted:
        event: token         data: {"text": "..."}
        event: tool_call     data: {"tool": "..."}
        event: hitl_request  data: {"interrupted": True, "next": [...]}
        event: done          data: {"agent": "...", "status": "success"}
        event: error         data: {"message": "..."}
    """
    trace_emitter.emit(
        session_id, "agent_start",
        agent=agent_name, is_internal=is_internal,
    )

    # create_agent expects:
    #   {"messages": [...]}  — fresh invocation
    #   None                 — resume from interrupt_before pause
    #   Command(resume=...)  — resume from langgraph.types.interrupt() pause (not used here)
    # The caller passes either a list[dict] or the _RESUME sentinel (object()).
    # We never double-wrap.
    if messages is None or not isinstance(messages, list):
        # None or any non-list sentinel → resume from interrupt_before
        inputs = None
    else:
        inputs = {"messages": messages}
    config = _thread_config(session_id)

    try:
        async for mode, chunk in agent.astream(
            inputs,
            config=config,
            stream_mode=["updates", "messages"],
        ):
            if mode == "messages":
                # chunk is (token, metadata).
                # The messages stream yields ALL message types including ToolMessage.
                # We must only forward AIMessage content as tokens — ToolMessage
                # content is raw tool output (JSON blobs, invoice arrays, ticket data)
                # that the model will summarise. Leaking it produces the technical
                # JSON the user sees in the chat bubble.
                token, metadata = chunk
                from langchain_core.messages import AIMessage as _AIMessage
                if not isinstance(token, _AIMessage):
                    continue
                content_blocks = getattr(token, "content_blocks", None)
                if content_blocks:
                    text = _text_from_content_blocks(content_blocks)
                    if text:
                        yield _sse("token", {"text": text})

            elif mode == "updates":
                # chunk is a state dict keyed by node name.
                # We emit tool_call events (model deciding to call a tool)
                # and tool_end traces (tool result arrived).
                # We NEVER emit ToolMessage content as a token — that is raw
                # tool output the model will summarise; leaking it to the
                # frontend causes hitl_pending JSON to appear as chat text.
                from langchain_core.messages import ToolMessage as _ToolMessage
                for node_name, node_data in chunk.items():
                    if not isinstance(node_data, dict):
                        continue
                    node_msgs = node_data.get("messages", [])
                    for msg in node_msgs:
                        # AIMessage with tool_calls → model is calling a tool
                        tool_calls = getattr(msg, "tool_calls", [])
                        for tc in tool_calls:
                            tool_name = tc.get("name", "")
                            trace_emitter.emit(
                                session_id, "tool_start",
                                agent=agent_name, tool=tool_name,
                            )
                            if not is_internal:
                                yield _sse("tool_call", {"tool": tool_name})

                        # ToolMessage → tool result arrived, trace only, never yield as token
                        if isinstance(msg, _ToolMessage):
                            trace_emitter.emit(
                                session_id, "tool_end",
                                agent=agent_name, tool=getattr(msg, "name", ""),
                            )

        # ── Check if graph paused at interrupt_before ─────────────────────────
        # With interrupt_before=["tools"], LangGraph stops the stream cleanly
        # (no exception). state.next = ("tools",) signals a pause.
        try:
            state = agent.get_state({"configurable": {"thread_id": session_id}})
            if state.next:
                yield _sse("hitl_request", {"interrupted": True, "next": list(state.next)})
                return
        except Exception:
            pass

        trace_emitter.emit(
            session_id, "agent_end",
            agent=agent_name, status="success", is_internal=is_internal,
        )
        if not is_internal:
            yield _sse("done", {"agent": agent_name, "status": "success"})

    except Exception as exc:
        trace_emitter.emit(session_id, "error", agent=agent_name, message=str(exc))
        yield _sse("error", {"message": str(exc)})


async def resume_agent(
    *,
    agent,
    session_id: str,
    agent_name: str,
) -> AsyncIterator[str]:
    """
    Resume a graph paused by interrupt_before.

    For interrupt_before graphs, pass None as the input to astream().
    This is distinct from langgraph.types.interrupt() pauses which use
    Command(resume=...). Using Command here causes 'resume_is_map referenced
    before assignment' inside LangGraph internals.
    """
    trace_emitter.emit(
        session_id, "hitl_resumed",
        agent=agent_name,
    )

    config = _thread_config(session_id)

    try:
        async for mode, chunk in agent.astream(
            None,
            config=config,
            stream_mode=["updates", "messages"],
        ):
            if mode == "messages":
                token, metadata = chunk
                from langchain_core.messages import AIMessage as _AIMessage
                if not isinstance(token, _AIMessage):
                    continue
                content_blocks = getattr(token, "content_blocks", None)
                if content_blocks:
                    text = _text_from_content_blocks(content_blocks)
                    if text:
                        yield _sse("token", {"text": text})

            elif mode == "updates":
                for node_name, node_data in chunk.items():
                    if not isinstance(node_data, dict):
                        continue
                    for msg in node_data.get("messages", []):
                        tool_calls = getattr(msg, "tool_calls", [])
                        for tc in tool_calls:
                            yield _sse("tool_call", {"tool": tc.get("name", "")})

        trace_emitter.emit(session_id, "agent_end", agent=agent_name, status="success")
        yield _sse("done", {"agent": agent_name, "status": "success"})

    except Exception as exc:
        trace_emitter.emit(session_id, "error", agent=agent_name, message=str(exc))
        yield _sse("error", {"message": str(exc)})


def _build_hitl_payload(interrupt_payloads) -> dict:
    """
    Build HITL SSE payload from LangGraph interrupt data.
    Read duck-typed — no hard import coupling to middleware internals.
    """
    if not interrupt_payloads:
        return {
            "question":       "Please confirm the requested action.",
            "ticket_preview": {},
            "options":        ["Yes", "No"],
        }

    first          = interrupt_payloads[0]
    action_request = getattr(first, "action_request", {})
    args           = getattr(action_request, "args", None) or action_request.get("args", {})

    title    = args.get("title",    "Support Ticket")
    category = args.get("category", "N/A")
    priority = args.get("priority", "N/A")

    return {
        "question": (
            f"I'd like to raise a support ticket on your behalf:\n\n"
            f"  Title:    {title}\n"
            f"  Category: {category}\n"
            f"  Priority: {priority}\n\n"
            f"Shall I go ahead and create it?"
        ),
        "ticket_preview": {
            "title":       title,
            "description": args.get("description", ""),
            "customer_id": args.get("customer_id"),
            "category":    category,
            "priority":    priority,
        },
        "options": ["Yes, raise it", "No, skip it"],
    }