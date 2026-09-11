"""Credential redaction must fire on real key shapes and never on ordinary output."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import router_redact as rr  # noqa: E402

SECRETS = [
    "sk-ant-api03-" + "A" * 90,
    "sk-proj-" + "b" * 40,
    "ghp_" + "c" * 36,
    "github_pat_" + "d" * 45,
    "glpat-" + "e" * 20,
    "AKIAIOSFODNN7EXAMPLE",
    "AIza" + "f" * 35,
    "xoxb-123456789012-abcdefghijkl",
    "hf_" + "g" * 34,
    "-----BEGIN RSA PRIVATE KEY-----",
]

# Things that must survive untouched: prose, code, hashes, paths, version strings.
INNOCENT = [
    "The sk- prefix identifies an OpenAI key, but this sentence has none.",
    "git commit 5da9ae1f2c3d4e5a6b7c8d9e0f1a2b3c4d5e6f70 touched the router.",
    "```python\nimport hashlib\nh = hashlib.sha256(b'abc').hexdigest()\n```",
    "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "/mnt/hfcache/huggingface/hub/models--bartowski--Ling-3.0-flash-GGUF/snapshot",
    "Base64 payload: TW96aWxsYS81LjAgKFgxMTsgTGludXggeDg2XzY0KQ==",
    "decode 31.6 t/s | prefill 425.7 t/s across 4 cards",
    "AKIA is the AWS prefix; ASIA is used for temporary credentials.",
]


def test_secrets_are_redacted():
    for s in SECRETS:
        out, n = rr.redact_text(f"here is the key: {s} -- do not share")
        assert n >= 1, f"missed: {s[:24]}"
        assert s not in out, f"leaked: {s[:24]}"
        assert "[redacted:" in out


def test_innocent_text_is_byte_identical():
    for text in INNOCENT:
        out, n = rr.redact_text(text)
        assert n == 0, f"false positive in: {text[:60]}"
        assert out == text


def test_streaming_reassembles_a_split_key():
    """A key arrives as many tokens; per-delta matching would never fire."""
    key = "sk-ant-api03-" + "Z" * 90
    deltas = ["Your key is ", "sk", "-ant", "-api", "03-"] + [
        key[13:][i : i + 7] for i in range(0, 90, 7)
    ]
    deltas.append(" -- keep it safe.")
    r = rr.StreamRedactor()
    out = "".join(r.feed(0, d) for d in deltas) + r.flush(0)
    assert key not in out
    assert "[redacted:anthropic]" in out
    assert out.startswith("Your key is ")
    assert out.endswith(" -- keep it safe.")
    assert r.hits == 1


def test_streaming_prose_is_not_delayed():
    """Ordinary text must pass straight through, or streaming visibly stutters."""
    r = rr.StreamRedactor()
    deltas = ["The ", "tidal ", "barrage ", "generates ", "power."]
    emitted = [r.feed(0, d) for d in deltas]
    assert emitted == deltas, "prose was buffered — would lag the stream"
    assert r.flush(0) == ""


def test_streaming_chunk_in_place():
    r = rr.StreamRedactor()
    chunk = {"choices": [{"index": 0, "delta": {"content": "key ghp_" + "h" * 36 + " end"}}]}
    assert r.feed_chunk(chunk) is True
    assert "ghp_" not in chunk["choices"][0]["delta"]["content"]
    assert r.hits == 1


def test_completion_redacted_but_tool_calls_untouched():
    args = '{"path": "sk-proj-' + "k" * 40 + '"}'
    comp = {
        "choices": [
            {
                "message": {
                    "content": "here: sk-proj-" + "k" * 40,
                    "tool_calls": [{"function": {"name": "read", "arguments": args}}],
                }
            }
        ]
    }
    hits = rr.redact_completion(comp)
    assert hits == 1
    assert "[redacted:openai]" in comp["choices"][0]["message"]["content"]
    # tool args deliberately left alone: rewriting them breaks the caller's JSON parse
    assert comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == args


def test_flush_emits_held_partial_that_never_completed():
    """A tail that looks like a key start but never becomes one must still be emitted."""
    r = rr.StreamRedactor()
    out = r.feed(0, "the prefix is sk-") + r.flush(0)
    assert out == "the prefix is sk-"
    assert r.hits == 0
