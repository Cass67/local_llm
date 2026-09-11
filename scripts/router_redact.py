"""Redact credentials from model output on the router's response path.

Forge and the per-repo guard already tell the model not to echo secrets; this is the
backstop for when it does it anyway, which is a failure mode that gets worse as the
instruction drifts back in a long context.

Design rule: **only high-confidence, prefixed credential formats.** No entropy or
base64 heuristics. A false positive silently corrupts model output — a mangled diff,
a broken code block — which is worse than a miss that the other two layers cover.
Every pattern here has a fixed vendor prefix and a length, so prose, code and hashes
cannot trip it.
"""

from __future__ import annotations

import re

# (name, pattern). Prefix + shape only.
_PATTERNS: list[tuple[str, str]] = [
    ("anthropic", r"sk-ant-(?:api|admin)[0-9]{2}-[A-Za-z0-9_\-]{24,}"),
    ("openai", r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}"),
    ("github", r"gh[pousr]_[A-Za-z0-9]{36,}"),
    ("github", r"github_pat_[A-Za-z0-9_]{40,}"),
    ("gitlab", r"glpat-[A-Za-z0-9_\-]{20,}"),
    ("aws", r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    ("google", r"AIza[0-9A-Za-z_\-]{35}"),
    ("slack", r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    ("huggingface", r"hf_[A-Za-z0-9]{34,}"),
    ("openrouter", r"sk-or-v1-[a-f0-9]{64}"),
    ("private-key", r"-----BEGIN[ A-Z]*PRIVATE KEY-----"),
]

# group names cannot contain "-", so index them and map back for the label
_GROUP_NAMES = [n for n, _ in _PATTERNS]
_SECRET_RE = re.compile("|".join(f"(?P<g{i}>{p})" for i, (_, p) in enumerate(_PATTERNS)))

# Literal starts of every pattern above. Used only to decide how much of a streamed
# delta to hold back, never to redact on its own.
_PREFIX_LITERALS = (
    "sk-ant-",
    "sk-proj-",
    "sk-svcacct-",
    "sk-or-v1-",
    "sk-",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
    "glpat-",
    "AKIA",
    "ASIA",
    "AIza",
    "xoxb-",
    "xoxa-",
    "xoxp-",
    "xoxr-",
    "xoxs-",
    "hf_",
    "-----BEGIN",
)
_MAX_PREFIX = max(len(p) for p in _PREFIX_LITERALS)
# A completed prefix followed by body characters running to the end of the buffer.
_PARTIAL_RE = re.compile(
    "(?:" + "|".join(re.escape(p) for p in _PREFIX_LITERALS) + r")[A-Za-z0-9_\-]*$"
)

# Longest credential we expect; caps how much tail we ever buffer.
_MAX_SECRET = 200


def _label(match: re.Match) -> str:
    g = match.lastgroup or ""
    idx = int(g[1:]) if g.startswith("g") and g[1:].isdigit() else -1
    return f"[redacted:{_GROUP_NAMES[idx] if idx >= 0 else 'secret'}]"


def _hold_from(buf: str) -> int | None:
    """Index from which `buf` must be held back, or None if all of it is safe to emit.

    Two cases: a credential prefix already completed and its body is still arriving,
    or the very end of the buffer is still growing into a prefix ("s", "sk", "sk-a").
    Missing the second case releases the buffer one character too early and the key
    streams out intact.
    """
    m = _PARTIAL_RE.search(buf)
    if m and len(buf) - m.start() <= _MAX_SECRET:
        return m.start()
    start = max(0, len(buf) - _MAX_PREFIX)
    for i in range(start, len(buf)):
        tail = buf[i:]
        if any(p.startswith(tail) for p in _PREFIX_LITERALS):
            return i
    return None


def redact_text(text: str) -> tuple[str, int]:
    """Return (redacted, n_hits). Byte-identical to input when nothing matches."""
    if not text:
        return text, 0
    hits = 0

    def sub(m: re.Match) -> str:
        nonlocal hits
        hits += 1
        return _label(m)

    return _SECRET_RE.sub(sub, text), hits


def redact_completion(completion: dict) -> int:
    """Redact a non-streaming chat completion in place. Returns hit count.

    Only message content and reasoning_content are touched. Tool-call arguments are
    left alone deliberately: rewriting them can break the caller's JSON parse, and a
    tool call is structured data the agent consumes, not text echoed to a screen.
    """
    hits = 0
    for choice in completion.get("choices") or []:
        msg = choice.get("message")
        if not isinstance(msg, dict):
            continue
        for field in ("content", "reasoning_content"):
            val = msg.get(field)
            if isinstance(val, str):
                new, n = redact_text(val)
                if n:
                    msg[field] = new
                    hits += n
    return hits


class StreamRedactor:
    """Redacts across streamed deltas, which arrive a few characters at a time.

    A key is emitted as many tokens ("sk", "-ant", "-api03", ...), so matching each
    delta in isolation never fires. This keeps a small per-choice carry buffer, but
    **only when the tail already looks like the start of a credential** — ordinary
    prose is emitted immediately with zero added latency, so streaming does not stutter.
    """

    def __init__(self) -> None:
        self._carry: dict[int, str] = {}
        self.hits = 0

    def feed(self, idx: int, text: str) -> str:
        """Feed one delta for choice `idx`; return the text safe to emit now."""
        buf = self._carry.pop(idx, "") + text
        buf, n = redact_text(buf)
        self.hits += n
        cut = _hold_from(buf)
        if cut is not None:
            self._carry[idx] = buf[cut:]
            return buf[:cut]
        return buf

    def flush(self, idx: int) -> str:
        """Emit whatever is still held for `idx` at end of stream."""
        buf = self._carry.pop(idx, "")
        if not buf:
            return ""
        buf, n = redact_text(buf)
        self.hits += n
        return buf

    def flush_all(self) -> str:
        return "".join(self.flush(i) for i in sorted(self._carry))

    def feed_chunk(self, chunk: dict) -> bool:
        """Redact an OpenAI streaming chunk in place. True if it was modified."""
        changed = False
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            idx = int(choice.get("index") or 0)
            for field in ("content", "reasoning_content"):
                val = delta.get(field)
                if isinstance(val, str) and val:
                    out = self.feed(idx, val)
                    if out != val:
                        delta[field] = out
                        changed = True
            if choice.get("finish_reason"):
                tail = self.flush(idx)
                if tail:
                    delta["content"] = (delta.get("content") or "") + tail
                    changed = True
        return changed
