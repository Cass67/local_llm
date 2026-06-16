#!/usr/bin/env python3
"""Pi agent — agentic chat client using DiffusionGemma on ubt26."""

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

HOST = os.environ.get("DIFFUSION_HOST", "ubt26")
PORT = int(os.environ.get("DIFFUSION_PORT", "8080"))
URL = f"http://{HOST}:{PORT}/v1/chat/completions"
TIMEOUT = 300

SYSTEM = """\
You are a helpful AI agent running on a Raspberry Pi. You can use tools by \
outputting XML tags. After using a tool you will receive the result and can \
continue reasoning. When you are done, reply normally without any tool tags.

Available tools:

<bash>command here</bash>
Run a shell command on the Raspberry Pi. Use for system info, files, network, etc.

<read>/absolute/path/to/file</read>
Read a file from the Pi filesystem.

<write path="/absolute/path">file content here</write>
Write content to a file on the Pi filesystem.

Rules:
- Use tools when you need real information, not when you can answer from memory.
- One tool per response, wait for result before using another.
- Never use bash for destructive operations without confirming with the user first.
- When done, give a clear final answer with no tool tags.
"""

_BASH_RE = re.compile(r"<bash>(.*?)</bash>", re.DOTALL)
_READ_RE = re.compile(r"<read>(.*?)</read>", re.DOTALL)
_WRITE_RE = re.compile(r'<write\s+path="([^"]+)">(.*?)</write>', re.DOTALL)


def _ask(messages: list) -> str:
    body = json.dumps({"messages": messages}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # nosec B310 -- internal URL
        return json.load(r)["choices"][0]["message"]["content"]


def _tool_bash(cmd: str) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)  # nosec B602 -- tool execution
    out = result.stdout + result.stderr
    return out.strip() or "(no output)"


def _tool_read(path: str) -> str:
    try:
        return Path(path.strip()).read_text()
    except Exception as e:
        return f"error: {e}"


def _tool_write(path: str, content: str) -> str:
    try:
        p = Path(path.strip())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"error: {e}"


def _run_tools(response: str) -> tuple[bool, str]:
    """Return (did_run_tool, tool_result_text)."""
    if m := _BASH_RE.search(response):
        cmd = m.group(1).strip()
        print(f"\n[bash] {cmd}")
        result = _tool_bash(cmd)
        print(f"[result]\n{result}")
        return True, f"<tool_result>\n{result}\n</tool_result>"

    if m := _READ_RE.search(response):
        path = m.group(1).strip()
        print(f"\n[read] {path}")
        result = _tool_read(path)
        return True, f"<tool_result>\n{result}\n</tool_result>"

    if m := _WRITE_RE.search(response):
        path, content = m.group(1), m.group(2)
        print(f"\n[write] {path}")
        result = _tool_write(path, content)
        print(f"[result] {result}")
        return True, f"<tool_result>\n{result}\n</tool_result>"

    return False, ""


def _agent_turn(history: list, user_input: str) -> str:
    history.append({"role": "user", "content": user_input})
    for _ in range(10):  # max tool iterations per turn
        print("thinking...", end="\r", flush=True)
        reply = _ask(history)
        print("           \r", end="", flush=True)
        history.append({"role": "assistant", "content": reply})

        used_tool, result = _run_tools(reply)
        if not used_tool:
            return reply

        history.append({"role": "user", "content": result})

    return "[max tool iterations reached]"


def main() -> None:
    print(f"Pi agent → {URL}")
    print("Ctrl-C or 'quit' to exit.\n")
    history: list[dict] = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            break
        try:
            reply = _agent_turn(history, user_input)
        except Exception as e:
            print(f"[error: {e}]")
            # rollback last user message
            while history and history[-1]["role"] != "assistant":
                history.pop()
            continue
        print(f"Assistant: {reply}\n")


if __name__ == "__main__":
    main()
