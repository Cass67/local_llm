"""OpenAI Responses API ↔ chat completions translation.

Codex CLI dropped chat-completions support in 0.146; it only speaks
/v1/responses. Pure functions here, wiring in model_router.py.
"""

import json
import time
import uuid

from router_chat import merge_system

_TEXT_PARTS = {"input_text", "output_text", "text", "summary_text"}


def _resp_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def _item_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _parts_to_content(content) -> str | list[dict]:
    """Responses content parts → chat content (string, or parts when images present)."""
    if isinstance(content, str):
        return content
    parts: list[dict] = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype in _TEXT_PARTS:
            parts.append({"type": "text", "text": part.get("text", "")})
        elif ptype == "input_image":
            url = part.get("image_url")
            if isinstance(url, dict):
                url = url.get("url", "")
            parts.append({"type": "image_url", "image_url": {"url": url or ""}})
    if parts and all(p["type"] == "text" for p in parts):
        return "".join(p["text"] for p in parts)
    return parts


def _item_to_message(item: dict) -> dict | None:
    """One Responses input item → one chat message (None for items we can't replay)."""
    itype = item.get("type", "message")
    if itype == "message":
        role = item.get("role", "user")
        return {
            "role": "system" if role == "developer" else role,
            "content": _parts_to_content(item.get("content")),
        }
    if itype == "function_call":
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": item.get("call_id") or item.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments") or "{}",
                    },
                }
            ],
        }
    if itype == "function_call_output":
        output = item.get("output")
        if isinstance(output, (dict, list)):
            output = json.dumps(output)
        return {"role": "tool", "tool_call_id": item.get("call_id", ""), "content": output or ""}
    # reasoning items carry no content we can replay
    return None


def _tools_to_chat(payload: dict, chat: dict) -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for tool in payload.get("tools") or []
        if tool.get("type") in ("function", None) and tool.get("name")
    ]
    if not tools:
        return
    chat["tools"] = tools
    choice = payload.get("tool_choice")
    if isinstance(choice, dict) and choice.get("name"):
        chat["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    elif isinstance(choice, str) and choice in ("auto", "none", "required"):
        chat["tool_choice"] = choice


def to_chat(payload: dict) -> dict:
    """Responses request → chat completions request."""
    messages: list[dict] = []
    if payload.get("instructions"):
        messages.append({"role": "system", "content": payload["instructions"]})

    items = payload.get("input")
    if isinstance(items, str):
        items = [{"type": "message", "role": "user", "content": items}]
    for item in items or []:
        if isinstance(item, dict):
            message = _item_to_message(item)
            if message is not None:
                messages.append(message)

    chat: dict = {"model": payload.get("model", ""), "messages": merge_system(messages)}
    for key in ("temperature", "top_p", "stream", "parallel_tool_calls"):
        if key in payload:
            chat[key] = payload[key]
    if payload.get("max_output_tokens"):
        chat["max_tokens"] = payload["max_output_tokens"]

    _tools_to_chat(payload, chat)

    return chat


def _output_items(message: dict) -> list[dict]:
    items: list[dict] = []
    text = message.get("content") or ""
    if text:
        items.append(
            {
                "type": "message",
                "id": _item_id(),
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        call_id = call.get("id") or f"call_{uuid.uuid4().hex[:24]}"
        items.append(
            {
                "type": "function_call",
                "id": _item_id("fc"),
                "call_id": call_id,
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments") or "{}",
                "status": "completed",
            }
        )
    return items


def _envelope(model: str, resp_id: str, status: str, output: list[dict], usage: dict) -> dict:
    return {
        "id": resp_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": usage.get("completion_tokens", 0),
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


def from_chat(completion: dict, model: str) -> dict:
    """Chat completions response → Responses object."""
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    status = "incomplete" if choice.get("finish_reason") == "length" else "completed"
    return _envelope(
        model, _resp_id(), status, _output_items(message), completion.get("usage") or {}
    )


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class ResponsesStream:
    """Chat completions SSE chunks → Responses SSE events.

    The Responses wire format is item-oriented: every message and tool call is
    an output item that must be announced, streamed, then completed. Text also
    needs a content part opened inside its item.
    """

    def __init__(self, model: str):
        self.model = model
        self.id = _resp_id()
        self.seq = 0
        self.out_index = 0
        self.text_item: str | None = None
        self.text = ""
        self.output: list[dict] = []  # completed items, ids reused in response.completed
        self.tools: dict[int, dict] = {}  # openai index → item state
        self.finish = "stop"
        self.usage: dict = {}

    def _emit(self, event: str, data: dict) -> bytes:
        data["type"] = event
        data["sequence_number"] = self.seq
        self.seq += 1
        return _sse(event, data)

    def start(self) -> bytes:
        base = _envelope(self.model, self.id, "in_progress", [], {})
        return self._emit("response.created", {"response": base}) + self._emit(
            "response.in_progress", {"response": dict(base)}
        )

    def _open_text(self) -> bytes:
        self.text_item = _item_id()
        out = self._emit(
            "response.output_item.added",
            {
                "output_index": self.out_index,
                "item": {
                    "type": "message",
                    "id": self.text_item,
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                },
            },
        )
        out += self._emit(
            "response.content_part.added",
            {
                "item_id": self.text_item,
                "output_index": self.out_index,
                "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
        )
        return out

    def _close_text(self) -> bytes:
        if self.text_item is None:
            return b""
        out = self._emit(
            "response.output_text.done",
            {
                "item_id": self.text_item,
                "output_index": self.out_index,
                "content_index": 0,
                "text": self.text,
            },
        )
        out += self._emit(
            "response.content_part.done",
            {
                "item_id": self.text_item,
                "output_index": self.out_index,
                "content_index": 0,
                "part": {"type": "output_text", "text": self.text, "annotations": []},
            },
        )
        item = {
            "type": "message",
            "id": self.text_item,
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": self.text, "annotations": []}],
        }
        out += self._emit(
            "response.output_item.done", {"output_index": self.out_index, "item": item}
        )
        self.output.append(item)
        self.out_index += 1
        self.text_item = None
        self.text = ""
        return out

    def chunk(self, data: dict) -> bytes:
        out = b""
        if data.get("usage"):
            self.usage = data["usage"]

        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if choice.get("finish_reason"):
            self.finish = choice["finish_reason"]

        text = delta.get("content")
        if text:
            if self.text_item is None:
                out += self._open_text()
            self.text += text
            out += self._emit(
                "response.output_text.delta",
                {
                    "item_id": self.text_item,
                    "output_index": self.out_index,
                    "content_index": 0,
                    "delta": text,
                },
            )

        for call in delta.get("tool_calls") or []:
            slot = call.get("index", 0)
            fn = call.get("function") or {}
            if slot not in self.tools:
                out += self._close_text()
                state = {
                    "item_id": _item_id("fc"),
                    "call_id": call.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                    "name": fn.get("name", ""),
                    "args": "",
                    "output_index": self.out_index,
                }
                self.tools[slot] = state
                self.out_index += 1
                out += self._emit(
                    "response.output_item.added",
                    {
                        "output_index": state["output_index"],
                        "item": {
                            "type": "function_call",
                            "id": state["item_id"],
                            "call_id": state["call_id"],
                            "name": state["name"],
                            "arguments": "",
                            "status": "in_progress",
                        },
                    },
                )
            state = self.tools[slot]
            if fn.get("name") and not state["name"]:
                state["name"] = fn["name"]
            args = fn.get("arguments")
            if args:
                state["args"] += args
                out += self._emit(
                    "response.function_call_arguments.delta",
                    {
                        "item_id": state["item_id"],
                        "output_index": state["output_index"],
                        "delta": args,
                    },
                )
        return out

    def stop(self) -> bytes:
        out = self._close_text()
        for state in self.tools.values():
            out += self._emit(
                "response.function_call_arguments.done",
                {
                    "item_id": state["item_id"],
                    "output_index": state["output_index"],
                    "arguments": state["args"],
                },
            )
            item = {
                "type": "function_call",
                "id": state["item_id"],
                "call_id": state["call_id"],
                "name": state["name"],
                "arguments": state["args"],
                "status": "completed",
            }
            out += self._emit(
                "response.output_item.done",
                {"output_index": state["output_index"], "item": item},
            )
            self.output.append(item)

        status = "incomplete" if self.finish == "length" else "completed"
        out += self._emit(
            "response.completed",
            {"response": _envelope(self.model, self.id, status, self.output, self.usage)},
        )
        return out


def error(message: str, code: str = "invalid_request_error") -> dict:
    return {"error": {"type": code, "message": message, "param": None, "code": None}}
