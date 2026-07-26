#!/usr/bin/env python3
"""Pi agent — agentic chat client using DiffusionGemma on ubt26."""

import base64
import json
import mimetypes
import os
import re
import subprocess
import urllib.request
from pathlib import Path

# Router, not a bare llama-server: it picks a vision-capable model when the
# conversation carries images, which a single runner on :8080 cannot do.
HOST = os.environ.get("DIFFUSION_HOST", "ubt26")
PORT = int(os.environ.get("DIFFUSION_PORT", "3200"))
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
Read a file from the Pi filesystem. Images (png/jpg/gif/webp/bmp) come back as
actual pictures you can see — use this to look at screenshots, never claim you
cannot read images.

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
    body = json.dumps({"model": "auto", "messages": messages}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # nosec B310 -- internal URL
        return json.load(r)["choices"][0]["message"]["content"]


def _tool_bash(cmd: str) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)  # nosec B602 -- tool execution
    out = result.stdout + result.stderr
    return out.strip() or "(no output)"


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _image_part(path: Path) -> dict:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def _tool_read(path: str) -> str | list[dict]:
    """Text files come back as text; images as an OpenAI image part the model can see."""
    try:
        p = Path(path.strip())
        if p.suffix.lower() in _IMAGE_SUFFIXES:
            return [
                {"type": "text", "text": f"<tool_result>image {p.name}</tool_result>"},
                _image_part(p),
            ]
        return p.read_text()
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


def _run_tools(response: str) -> tuple[bool, str | list[dict]]:
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
        if isinstance(result, list):
            return True, result
        return True, f"<tool_result>\n{result}\n</tool_result>"

    if m := _WRITE_RE.search(response):
        path, content = m.group(1), m.group(2)
        print(f"\n[write] {path}")
        result = _tool_write(path, content)
        print(f"[result] {result}")
        return True, f"<tool_result>\n{result}\n</tool_result>"

    return False, ""


_PATH_RE = re.compile(r"(?:~|/)[^\s'\"]+")


def _user_content(text: str) -> str | list[dict]:
    """Attach any image paths the user mentioned, so dragged-in screenshots are seen."""
    parts = []
    for raw in _PATH_RE.findall(text):
        p = Path(raw).expanduser()
        if p.suffix.lower() in _IMAGE_SUFFIXES and p.is_file():
            parts.append(_image_part(p))
    return [{"type": "text", "text": text}, *parts] if parts else text


def _agent_turn(history: list, user_input: str) -> str:
    history.append({"role": "user", "content": _user_content(user_input)})
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
