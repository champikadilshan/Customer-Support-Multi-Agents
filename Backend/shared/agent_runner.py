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
    if not content_blocks:
        return ""

    return "".join(
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )


async def stream_agent_events( *,agent,messages, agent_name: str,session_id: str,is_internal: bool = False,) -> AsyncIterator[str]:
    trace_emitter.emit(
        session_id, "agent_start",
        agent=agent_name,
        is_internal=is_internal,
    )

    if messages is None or not isinstance(messages, list):
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
                from langchain_core.messages import ToolMessage as _ToolMessage

                for node_name, node_data in chunk.items():
                    if not isinstance(node_data, dict):
                        continue

                    node_msgs = node_data.get("messages", [])

                    for msg in node_msgs:
                        tool_calls = getattr(msg, "tool_calls", [])

                        for tc in tool_calls:
                            tool_name = tc.get("name", "")

                            trace_emitter.emit(
                                session_id, "tool_start",
                                agent=agent_name,
                                tool=tool_name,
                            )

                            if not is_internal:
                                yield _sse("tool_call", {"tool": tool_name})

                        if isinstance(msg, _ToolMessage):
                            trace_emitter.emit(
                                session_id, "tool_end",
                                agent=agent_name,
                                tool=getattr(msg, "name", ""),
                            )

        try:
            state = agent.get_state({"configurable": {"thread_id": session_id}})

            if state.next:
                yield _sse("hitl_request", {"interrupted": True, "next": list(state.next)})
                return

        except Exception:
            pass

        trace_emitter.emit(
            session_id, "agent_end",
            agent=agent_name,
            status="success",
            is_internal=is_internal,
        )

        if not is_internal:
            yield _sse("done", {"agent": agent_name, "status": "success"})

    except Exception as exc:
        trace_emitter.emit(session_id, "error", agent=agent_name, message=str(exc))
        yield _sse("error", {"message": str(exc)})


async def resume_agent(*,agent,session_id: str,agent_name: str,) -> AsyncIterator[str]:
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