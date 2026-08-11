"""Anthropic Messages API ↔ OpenAI chat completions translation.

Claude Code speaks /v1/messages; llama.cpp speaks /v1/chat/completions. Pure
functions here, wiring in model_router.py.
"""

import json
import uuid

from router_chat import merge_system

_STOP_REASON = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "end_turn",
}


def _flatten_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"
    )


def _image_url(source: dict) -> str:
    if source.get("type") == "url":
        return source.get("url", "")
    return f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"


def _blocks_to_messages(role: str, content) -> list[dict]:
    """One Anthropic turn → one or more chat messages.

    tool_result blocks cannot ride along in a user message; each becomes its own
    tool message, emitted ahead of whatever text shared the turn.
    """
    if isinstance(content, str):
        return [{"role": role, "content": content}]

    messages: list[dict] = []
    parts: list[dict] = []
    tool_calls: list[dict] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            parts.append(
                {"type": "image_url", "image_url": {"url": _image_url(block.get("source") or {})}}
            )
        elif btype == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
            )
        elif btype == "tool_result":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": _flatten_text(block.get("content")),
                }
            )

    text = "".join(p["text"] for p in parts if p["type"] == "text")
    if tool_calls:
        messages.append({"role": role, "content": text or None, "tool_calls": tool_calls})
    elif parts:
        only_text = all(p["type"] == "text" for p in parts)
        messages.append({"role": role, "content": text if only_text else parts})
    return messages


def _tools_to_chat(payload: dict, chat: dict) -> None:
    chat["tools"] = [
        {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in payload["tools"]
        if t.get("name")
    ]
    choice = payload.get("tool_choice") or {}
    ctype = choice.get("type")
    if ctype == "any":
        chat["tool_choice"] = "required"
    elif ctype == "tool" and choice.get("name"):
        chat["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    elif ctype == "none":
        chat["tool_choice"] = "none"
    else:
        chat["tool_choice"] = "auto"


def to_chat(payload: dict) -> dict:
    """Anthropic request → chat completions request."""
    messages: list[dict] = []
    if payload.get("system"):
        messages.append({"role": "system", "content": _flatten_text(payload["system"])})
    for msg in payload.get("messages", []):
        messages += _blocks_to_messages(msg.get("role", "user"), msg.get("content"))

    chat: dict = {"model": payload.get("model", ""), "messages": merge_system(messages)}
    if payload.get("max_tokens"):
        chat["max_tokens"] = payload["max_tokens"]
    for key in ("temperature", "top_p", "stream"):
        if key in payload:
            chat[key] = payload[key]
    if payload.get("top_k"):
        chat["top_k"] = payload["top_k"]
    if payload.get("stop_sequences"):
        chat["stop"] = payload["stop_sequences"]

    if payload.get("tools"):
        _tools_to_chat(payload, chat)

    return chat


def _msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def from_chat(completion: dict, model: str) -> dict:
    """Chat completions response → Anthropic message."""
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content: list[dict] = []

    text = message.get("content") or ""
    if text:
        content.append({"type": "text", "text": text})

    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        content.append(
            {
                "type": "tool_use",
                "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                "name": fn.get("name", ""),
                "input": args,
            }
        )

    if not content:
        content.append({"type": "text", "text": ""})

    usage = completion.get("usage") or {}
    return {
        "id": completion.get("id") or _msg_id(),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": _STOP_REASON.get(choice.get("finish_reason") or "stop", "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class AnthropicStream:
    """Chat completions SSE chunks → Anthropic SSE events.

    Anthropic frames every piece of content as an indexed block that must be
    opened and closed; OpenAI just streams deltas. This tracks which block is
    open so text and tool calls get their own start/stop pairs.
    """

    def __init__(self, model: str):
        self.model = model
        self.index = -1
        self.open_kind: str | None = None  # "text" | "tool"
        self.tool_slots: dict[int, int] = {}  # openai tool_calls index → block index
        self.finish = "stop"
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def start(self) -> bytes:
        # A cold cluster can take 30s+ to produce its first token, and an SSE
        # connection that sends nothing in that window gets closed by
        # intermediaries. The ping is bytes on the wire while the model loads.
        return _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": _msg_id(),
                    "type": "message",
                    "role": "assistant",
                    "model": self.model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        ) + _sse("ping", {"type": "ping"})

    def _close_open(self) -> bytes:
        if self.open_kind is None:
            return b""
        out = _sse("content_block_stop", {"type": "content_block_stop", "index": self.index})
        self.open_kind = None
        return out

    def chunk(self, data: dict) -> bytes:
        out = b""
        usage = data.get("usage") or {}
        if usage:
            self.usage = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }

        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if choice.get("finish_reason"):
            self.finish = choice["finish_reason"]

        text = delta.get("content")
        if text:
            if self.open_kind != "text":
                out += self._close_open()
                self.index += 1
                self.open_kind = "text"
                out += _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": self.index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            out += _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self.index,
                    "delta": {"type": "text_delta", "text": text},
                },
            )

        for call in delta.get("tool_calls") or []:
            slot = call.get("index", 0)
            fn = call.get("function") or {}
            if slot not in self.tool_slots:
                out += self._close_open()
                self.index += 1
                self.tool_slots[slot] = self.index
                self.open_kind = "tool"
                out += _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": self.index,
                        "content_block": {
                            "type": "tool_use",
                            "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                            "name": fn.get("name", ""),
                            "input": {},
                        },
                    },
                )
            args = fn.get("arguments")
            if args:
                out += _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": self.tool_slots[slot],
                        "delta": {"type": "input_json_delta", "partial_json": args},
                    },
                )
        return out

    def stop(self) -> bytes:
        out = self._close_open()
        out += _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": _STOP_REASON.get(self.finish, "end_turn"),
                    "stop_sequence": None,
                },
                "usage": self.usage,
            },
        )
        out += _sse("message_stop", {"type": "message_stop"})
        return out


def count_tokens(payload: dict) -> dict:
    """Rough estimate — Claude Code only uses this for context-budget display."""
    chars = len(_flatten_text(payload.get("system") or ""))
    for msg in payload.get("messages", []):
        content = msg.get("content")
        if isinstance(content, str):
            chars += len(content)
            continue
        for block in content or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                chars += len(block.get("text", ""))
            elif block.get("type") == "tool_use":
                chars += len(json.dumps(block.get("input") or {}))
            elif block.get("type") == "tool_result":
                chars += len(_flatten_text(block.get("content")))
    chars += len(json.dumps(payload.get("tools") or []))
    return {"input_tokens": max(1, chars // 4)}


def error(message: str, err_type: str = "invalid_request_error") -> dict:
    return {"type": "error", "error": {"type": err_type, "message": message}}
