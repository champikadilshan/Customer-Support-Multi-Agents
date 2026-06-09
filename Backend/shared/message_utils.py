"""
shared/message_utils.py
-----------------------
Helpers to convert between LangChain BaseMessage objects and the plain-dict
format used in session storage and A2ARequest/A2AResponse.

Dict schema
-----------
    Human  : {"type": "human",  "content": "<text>"}
    AI     : {"type": "ai",     "content": "<text>",  "tool_calls": [...]}   # tool_calls optional
    Tool   : {"type": "tool",   "content": "<text>",  "name": "<tool_name>", "tool_call_id": "..."}
"""

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)


# ── Serialise ─────────────────────────────────────────────────────────────────

def messages_to_dicts(messages: list[BaseMessage]) -> list[dict]:
    """Convert a list of LangChain messages to plain dicts for storage / transport."""
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"type": "human", "content": _str_content(msg.content)})

        elif isinstance(msg, AIMessage):
            entry: dict = {"type": "ai", "content": _str_content(msg.content)}
            # Preserve tool_calls so the next agent turn can reconstruct context
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            result.append(entry)

        elif isinstance(msg, ToolMessage):
            result.append({
                "type":         "tool",
                "content":      _str_content(msg.content),
                "name":         msg.name or "",
                "tool_call_id": msg.tool_call_id or "",
            })

        # Any other message type (SystemMessage etc.) is intentionally skipped —
        # system prompts are rebuilt fresh on every agent invocation.

    return result


# ── Deserialise ───────────────────────────────────────────────────────────────

def dicts_to_messages(dicts: list[dict]) -> list[BaseMessage]:
    """Reconstruct LangChain BaseMessage objects from stored plain dicts."""
    result: list[BaseMessage] = []
    for d in dicts:
        t = d.get("type", "")
        content = d.get("content", "")

        if t == "human":
            result.append(HumanMessage(content=content))

        elif t == "ai":
            tool_calls = d.get("tool_calls")
            if tool_calls:
                result.append(AIMessage(content=content, tool_calls=tool_calls))
            else:
                result.append(AIMessage(content=content))

        elif t == "tool":
            result.append(ToolMessage(
                content=content,
                name=d.get("name", ""),
                tool_call_id=d.get("tool_call_id", ""),
            ))

    return result


# ── Internal ──────────────────────────────────────────────────────────────────

def _str_content(content) -> str:
    """Flatten multi-block content to a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)