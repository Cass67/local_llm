"""The redactor is reached from the router's response paths, not just importable.

The unit tests in test_router_redact.py prove the patterns work. These prove the
wiring: a key split across SSE deltas is caught, and the stream is re-framed
byte-identically when nothing matches.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import model_router as mr  # noqa: E402
import router_redact as rr  # noqa: E402

KEY = "sk-ant-api03-" + "Z" * 90


def _sse(deltas: list[str]) -> list[str]:
    lines = []
    for d in deltas:
        lines.append("data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": d}}]}))
        lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    return lines


class _FakeUpstream:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _drain(lines: list[str]) -> str:
    """Drive the exact helper _proxy_stream uses, over a canned upstream."""
    upstream = _FakeUpstream(lines)

    async def run():
        redactor = rr.StreamRedactor()
        out = []
        async for line in upstream.aiter_lines():
            out.extend((o + "\n").encode("utf-8") for o in mr._redact_sse_lines(line, redactor))
        return b"".join(out).decode()

    return asyncio.run(run())


def test_router_imports_the_redactor():
    assert mr.router_redact is rr


def test_split_key_across_deltas_is_redacted_in_stream():
    deltas = ["Your key is ", "sk", "-ant", "-api", "03-"] + [
        KEY[13:][i : i + 7] for i in range(0, 90, 7)
    ]
    body = _drain(_sse(deltas))
    assert KEY not in body
    assert "sk-ant-api03-ZZZ" not in body
    assert "[redacted:anthropic]" in body
    # The body is uniform, so "KEY not in body" alone still passes when only the
    # first 24 chars were replaced and the rest streamed out delta by delta.
    assert "ZZZZ" not in body


def test_held_text_is_flushed_at_done_without_a_finish_reason():
    """A stream that ends without finish_reason must still emit what was held."""
    body = _drain(_sse(["Key: ", "sk-ant-api03-", "A" * 40]))
    assert "[redacted:anthropic]" in body
    assert "AAAA" not in body


def test_clean_stream_is_reframed_unchanged():
    lines = _sse(["Hello ", "world, ", "no secrets here."])
    body = _drain(lines)
    assert body == "\n".join(lines) + "\n"
    assert "data: [DONE]" in body


def test_nonstream_completion_is_redacted():
    completion = {"choices": [{"message": {"role": "assistant", "content": f"use {KEY} now"}}]}
    assert rr.redact_completion(completion) == 1
    assert KEY not in completion["choices"][0]["message"]["content"]


def test_tool_call_arguments_are_left_alone():
    """Rewriting structured args breaks the caller's JSON parse; deliberate miss."""
    args = json.dumps({"token": KEY})
    completion = {
        "choices": [
            {"message": {"content": None, "tool_calls": [{"function": {"arguments": args}}]}}
        ]
    }
    rr.redact_completion(completion)
    assert completion["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == args
