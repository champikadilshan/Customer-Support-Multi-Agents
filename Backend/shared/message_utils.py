from langchain_core.messages import ( BaseMessage,HumanMessage, AIMessage,ToolMessage,)


def messages_to_dicts(messages: list[BaseMessage]) -> list[dict]:
    result = []

    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"type": "human", "content": _str_content(msg.content)})

        elif isinstance(msg, AIMessage):
            entry: dict = {"type": "ai", "content": _str_content(msg.content)}
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

    return result


def dicts_to_messages(dicts: list[dict]) -> list[BaseMessage]:
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


def _str_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)

    return str(content)