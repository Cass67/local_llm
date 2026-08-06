"""Anthropic /v1/messages and OpenAI /v1/responses translate to chat completions."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import router_anthropic as ant  # noqa: E402
import router_responses as resp  # noqa: E402


def _events(blob: bytes) -> list[tuple[str, dict]]:
    out = []
    for chunk in blob.decode().split("\n\n"):
        if not chunk.strip():
            continue
        name = chunk.split("\n")[0].removeprefix("event: ")
        data = json.loads(chunk.split("data: ", 1)[1])
        out.append((name, data))
    return out


# --- anthropic ---


def test_anthropic_system_and_blocks_to_chat():
    chat = ant.to_chat(
        {
            "model": "claude-opus-4-5",
            "max_tokens": 100,
            "system": [{"type": "text", "text": "be terse"}],
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "ls", "input": {"p": "."}}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "a.txt"},
                        {"type": "text", "text": "now what"},
                    ],
                },
            ],
            "tools": [{"name": "ls", "description": "list", "input_schema": {"type": "object"}}],
        }
    )
    assert chat["messages"][0] == {"role": "system", "content": "be terse"}
    assert chat["messages"][1] == {"role": "user", "content": "hi"}
    call = chat["messages"][2]["tool_calls"][0]
    assert call["id"] == "t1" and json.loads(call["function"]["arguments"]) == {"p": "."}
    # tool_result becomes its own message, ahead of the remaining user text
    assert chat["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": "a.txt"}
    assert chat["messages"][4] == {"role": "user", "content": "now what"}
    assert chat["tools"][0]["function"]["name"] == "ls"
    assert chat["max_tokens"] == 100


def test_anthropic_image_block_to_chat():
    chat = ant.to_chat(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this"},
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
                        },
                    ],
                }
            ]
        }
    )
    parts = chat["messages"][0]["content"]
    assert parts[1]["image_url"]["url"] == "data:image/png;base64,AAAA"


def test_anthropic_response_from_chat():
    msg = ant.from_chat(
        {
            "id": "chatcmpl-1",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "running it",
                        "tool_calls": [
                            {"id": "c1", "function": {"name": "ls", "arguments": '{"p":"."}'}}
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        },
        "local-model",
    )
    assert msg["stop_reason"] == "tool_use"
    assert msg["content"][0] == {"type": "text", "text": "running it"}
    assert msg["content"][1] == {"type": "tool_use", "id": "c1", "name": "ls", "input": {"p": "."}}
    assert msg["usage"] == {"input_tokens": 12, "output_tokens": 5}


def test_anthropic_stream_opens_and_closes_each_block():
    s = ant.AnthropicStream("local-model")
    blob = s.start()
    blob += s.chunk({"choices": [{"delta": {"content": "he"}}]})
    blob += s.chunk({"choices": [{"delta": {"content": "llo"}}]})
    blob += s.chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {"name": "ls", "arguments": '{"p"'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    blob += s.chunk(
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ':"."}'}}]},
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }
    )
    blob += s.stop()

    names = [name for name, _ in _events(blob)]
    assert names[0] == "message_start"
    assert names[-2:] == ["message_delta", "message_stop"]
    # text block opened, closed before the tool block opens, tool block closed at stop
    assert names.count("content_block_start") == 2
    assert names.count("content_block_stop") == 2
    assert names.index("content_block_stop") < names.index("content_block_start", 2)

    events = dict(enumerate(_events(blob)))
    tool_args = "".join(
        d["delta"]["partial_json"]
        for _, d in events.values()
        if d.get("type") == "content_block_delta" and d["delta"]["type"] == "input_json_delta"
    )
    assert json.loads(tool_args) == {"p": "."}
    stop = [d for n, d in _events(blob) if n == "message_delta"][0]
    assert stop["delta"]["stop_reason"] == "tool_use"
    assert stop["usage"] == {"input_tokens": 11, "output_tokens": 7}


def test_anthropic_count_tokens_is_positive():
    assert (
        ant.count_tokens({"messages": [{"role": "user", "content": "x" * 40}]})["input_tokens"] > 0
    )


# --- responses ---


def test_responses_input_items_to_chat():
    chat = resp.to_chat(
        {
            "model": "gpt-5",
            "instructions": "be terse",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hi"}],
                },
                {"type": "function_call", "call_id": "c1", "name": "ls", "arguments": '{"p":"."}'},
                {"type": "function_call_output", "call_id": "c1", "output": "a.txt"},
            ],
            "tools": [{"type": "function", "name": "ls", "parameters": {"type": "object"}}],
        }
    )
    assert chat["messages"][0] == {"role": "system", "content": "be terse"}
    assert chat["messages"][1] == {"role": "user", "content": "hi"}
    assert chat["messages"][2]["tool_calls"][0]["id"] == "c1"
    assert chat["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "a.txt"}
    assert chat["tools"][0]["function"]["name"] == "ls"


def test_responses_merges_instructions_and_developer_into_one_system():
    chat = resp.to_chat(
        {
            "instructions": "top",
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "rules"}],
                },
                {"type": "message", "role": "user", "content": "hi"},
            ],
        }
    )
    # a second system message makes Qwen's chat template raise
    assert [m["role"] for m in chat["messages"]] == ["system", "user"]
    assert chat["messages"][0]["content"] == "top\n\nrules"


def test_anthropic_system_role_message_is_not_left_mid_conversation():
    chat = ant.to_chat(
        {
            "system": "top",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "system", "content": "<system-reminder>"},
            ],
        }
    )
    assert [m["role"] for m in chat["messages"]] == ["system", "user", "user"]


def test_responses_plain_string_input():
    chat = resp.to_chat({"model": "gpt-5", "input": "hello"})
    assert chat["messages"] == [{"role": "user", "content": "hello"}]


def test_responses_from_chat_builds_output_items():
    out = resp.from_chat(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "ok",
                        "tool_calls": [{"id": "c1", "function": {"name": "ls", "arguments": "{}"}}],
                    },
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        },
        "local-model",
    )
    assert out["status"] == "completed"
    assert out["output"][0]["content"][0]["text"] == "ok"
    assert out["output"][1]["call_id"] == "c1"
    assert out["usage"]["total_tokens"] == 7


def test_responses_stream_event_order():
    s = resp.ResponsesStream("local-model")
    blob = s.start()
    blob += s.chunk({"choices": [{"delta": {"content": "he"}}]})
    blob += s.chunk({"choices": [{"delta": {"content": "llo"}}]})
    blob += s.chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "c1", "function": {"name": "ls", "arguments": "{}"}}
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
    )
    blob += s.stop()

    events = _events(blob)
    names = [n for n, _ in events]
    assert names[0] == "response.created"
    assert names[1] == "response.in_progress"
    assert names[-1] == "response.completed"
    # the text item must be completed before the function call item opens
    added = [i for i, n in enumerate(names) if n == "response.output_item.added"]
    assert names.index("response.output_item.done") < added[1]
    assert "response.function_call_arguments.done" in names

    # sequence numbers are contiguous and ordered
    seqs = [d["sequence_number"] for _, d in events]
    assert seqs == list(range(len(seqs)))

    final = events[-1][1]["response"]
    assert final["output"][0]["content"][0]["text"] == "hello"
    assert final["output"][1]["name"] == "ls"
    assert final["usage"]["input_tokens"] == 1

    # ids in response.completed must be the ones already announced, or Codex
    # drops the items and renders nothing
    announced = [d["item"]["id"] for n, d in events if n == "response.output_item.added"]
    assert [item["id"] for item in final["output"]] == announced


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
