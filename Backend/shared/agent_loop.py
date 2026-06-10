import asyncio
import json
import time

from typing import AsyncIterator, Any
from langchain_core.messages import (BaseMessage, AIMessage, ToolMessage, HumanMessage,)
from shared.trace_emitter import trace_emitter

MAX_ITERATIONS = 12 # Maximum iterations before hard stop — prevents infinite loops


def _extract_text(content: Any) -> str:
    """Flatten multi-block content to plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)

    return str(content) if content else ""


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _execute_tool(tool_call: dict,tool_map:  dict,agent_name: str, session_id: str, is_internal: bool,) -> ToolMessage:
    name    = tool_call.get("name", "")
    args    = tool_call.get("args", {})
    call_id = tool_call.get("id", "")

    start = time.monotonic()
    trace_emitter.emit(session_id, "tool_start", agent=agent_name, tool=name)

    try:
        fn = tool_map.get(name)

        if fn is None:
            result = f"[Tool '{name}' not found]"
        else:
            try:
                result = await fn.ainvoke(args)
            except (AttributeError, NotImplementedError):
                result = await asyncio.to_thread(fn.invoke, args)

        if isinstance(result, (dict, list)):
            result_str = json.dumps(result)
        else:
            result_str = str(result)

    except Exception as exc:
        result_str = f"[Tool error: {exc}]"

    duration_ms = int((time.monotonic() - start) * 1000)
    trace_emitter.emit(session_id, "tool_end",agent=agent_name, tool=name, duration_ms=duration_ms)

    return ToolMessage(content=result_str, name=name, tool_call_id=call_id)


async def run_agent_loop(*, llm_with_tools,messages: list[BaseMessage],tool_map: dict,agent_name: str,session_id: str, is_internal: bool = False,max_iterations: int  = MAX_ITERATIONS,) -> AsyncIterator[str]:
    current_messages = list(messages)
    iteration        = 0

    try:
        while iteration < max_iterations:
            iteration += 1

            response: AIMessage = await asyncio.to_thread(llm_with_tools.invoke, current_messages)

            text = _extract_text(response.content)
            if text:
                yield _sse("token", {"text": text})

            current_messages.append(response)

            tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []

            if not tool_calls and hasattr(response, "additional_kwargs"):
                raw = response.additional_kwargs.get("tool_calls", [])
                if raw:
                    tool_calls = [
                        {
                            "id":   tc.get("id", ""),
                            "name": tc.get("function", {}).get("name", ""),
                            "args": json.loads(tc.get("function", {}).get("arguments", "{}")),
                        }
                        for tc in raw
                    ]

            if not tool_calls:
                break

            for tc in tool_calls:
                tool_name = tc.get("name", "")
                trace_emitter.emit(session_id, "tool_start",
                                   agent=agent_name, tool=tool_name)
                if not is_internal:
                    yield _sse("tool_call", {"tool": tool_name})

            staged_call = next((tc for tc in tool_calls if tc.get("name") == "stage_ticket_creation"), None,)

            if staged_call and not is_internal:

                tool_msg = await _execute_tool( staged_call, tool_map, agent_name, session_id, is_internal)

                current_messages.append(tool_msg)

                try:
                    ticket_data = json.loads(tool_msg.content)
                except (json.JSONDecodeError, TypeError):
                    ticket_data = {}

                yield _sse("hitl_request", {
                    "question": (
                        f"I'd like to raise a support ticket on your behalf:\n\n"
                        f"  Title:    {ticket_data.get('title', 'Support Ticket')}\n"
                        f"  Category: {ticket_data.get('category', 'N/A')}\n"
                        f"  Priority: {ticket_data.get('priority', 'N/A')}\n\n"
                        f"Shall I go ahead and create it?"
                    ),
                    "ticket_preview": {
                        "title":       ticket_data.get("title"),
                        "description": ticket_data.get("description"),
                        "customer_id": ticket_data.get("customer_id"),
                        "category":    ticket_data.get("category"),
                        "priority":    ticket_data.get("priority"),
                    },
                    "options":            ["Yes, raise it", "No, skip it"],
                    "pending_messages":   _messages_to_dicts(current_messages),
                })

                return

            tasks = [_execute_tool(tc, tool_map, agent_name, session_id, is_internal)for tc in tool_calls]
            tool_messages: list[ToolMessage] = await asyncio.gather(*tasks)

            for tm in tool_messages:
                current_messages.append(tm)

            if not is_internal:
                for tm in tool_messages:
                    try:
                        result_data = json.loads(tm.content)
                        if isinstance(result_data, dict) and result_data.get("hitl_pending"):
                            trace_emitter.emit(session_id, "hitl_requested", agent=agent_name, ticket_preview=result_data.get("ticket_preview", {}))

                            yield _sse("hitl_request", {
                                "question":       result_data.get("question", ""),
                                "ticket_preview": result_data.get("ticket_preview", {}),
                                "options":        result_data.get("options", ["Yes", "No"]),
                                "request_id":     result_data.get("request_id", ""),
                            })

                            trace_emitter.emit(session_id, "agent_end",  agent=agent_name, status="hitl_suspended",is_internal=False)

                            return

                    except (json.JSONDecodeError, TypeError):
                        pass

        trace_emitter.emit(session_id, "agent_end", agent=agent_name, status="success", is_internal=is_internal)

        if not is_internal:
            yield _sse("done", {
                "agent":  agent_name,
                "status": "success",
            })

    except Exception as exc:
        trace_emitter.emit(session_id, "error", agent=agent_name, message=str(exc))
        yield _sse("error", {"message": str(exc)})


def _messages_to_dicts(messages: list[BaseMessage]) -> list[dict]:
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"type": "human", "content": _extract_text(msg.content)})
        elif isinstance(msg, AIMessage):
            entry: dict = {"type": "ai", "content": _extract_text(msg.content)}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            result.append(entry)
        elif isinstance(msg, ToolMessage):
            result.append({
                "type":         "tool",
                "content":      _extract_text(msg.content),
                "name":         msg.name or "",
                "tool_call_id": msg.tool_call_id or "",
            })
    return result


def get_final_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            text = _extract_text(msg.content)
            if text:
                return text

    return ""