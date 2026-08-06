"""Shaping shared by both protocol adapters before handing off to llama.cpp."""


def merge_system(messages: list[dict]) -> list[dict]:
    """Fold the leading system run into one message; demote any later ones.

    Both dialects can produce several system messages — Codex sends
    `instructions` plus `developer` items, Claude Code sends a `system` field
    plus system-role reminders. Qwen's chat template raises "System message must
    be at the beginning" on the second one, so they have to collapse.
    """
    lead: list[str] = []
    rest: list[dict] = []
    for msg in messages:
        if msg.get("role") != "system":
            rest.append(msg)
            continue
        text = msg.get("content")
        if not rest and isinstance(text, str):
            lead.append(text)
        else:
            rest.append({**msg, "role": "user"})
    if not lead:
        return rest
    return [{"role": "system", "content": "\n\n".join(lead)}, *rest]
