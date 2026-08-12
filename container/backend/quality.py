"""Golden-prompt quality checks.

Throughput benchmarks cannot see a config that got faster by getting worse — a
draft p_min that halves prose, a KV quant that makes the model repeat itself, a
speculative setting that truncates. This module runs a small fixed prompt set and
scores the output, so a sweep or a rebuild has something to fail on besides tok/s.

Two layers, cheap first: deterministic checks catch degenerate output with no
second model involved; the optional judge grades whether the answer is any good.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import config

logger = logging.getLogger(__name__)

# Deliberately small and fixed. Each case targets a failure mode that throughput
# numbers hide, not general capability — that is what terminal-bench is for.
DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "id": "code-basic",
        "prompt": "Write a Python function `is_palindrome(s)` that ignores case and "
        "non-alphanumeric characters. Return only code.",
        "min_words": 20,
        "must_match": [r"def\s+is_palindrome"],
    },
    {
        "id": "code-echo-edit",
        "prompt": "Here is a function:\n\ndef add(a, b):\n    return a + b\n\n"
        "Rewrite it to accept any number of arguments, keeping the same style. "
        "Return only the code.",
        "min_words": 8,
        "must_match": [r"def\s+add"],
    },
    {
        "id": "prose-length",
        "prompt": "Explain in three full paragraphs why memory bandwidth, not compute, "
        "usually limits single-stream LLM token generation.",
        # Speculative-decoding misconfiguration shows up here first, as prose that
        # stops at a third of the length it should be.
        "min_words": 150,
    },
    {
        "id": "instruction-format",
        "prompt": "List exactly five prime numbers greater than 100, one per line, "
        "with no other text.",
        "min_words": 5,
        "must_match": [r"\b(101|103|107|109|113|127|131|137|139|149)\b"],
    },
    {
        "id": "long-context-recall",
        "prompt": "Remember this token: ZEPHYR-4417.\n\n"
        + ("Filler sentence about unrelated matters. " * 200)
        + "\n\nWhat was the token?",
        "min_words": 1,
        "must_match": [r"ZEPHYR-4417"],
    },
    {
        "id": "refusal-check",
        "prompt": "What is 17 * 23? Answer with the number only.",
        "min_words": 1,
        "must_match": [r"391"],
    },
]

MAX_REPETITION_RATIO = 0.35  # share of output made of one repeated line/phrase
JUDGE_RUBRIC = (
    "You are grading a model's answer. Score 1-5 where 1 is unusable and 5 is "
    "correct, complete, and well-formed. Reply with only the digit."
)


def load_cases() -> list[dict[str, Any]]:
    """Defaults, or the user's set from state if they have written one."""
    path = config.STATE_DIR / "quality_set.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CASES
    cases = data.get("cases") if isinstance(data, dict) else data
    if isinstance(cases, list) and cases:
        return [c for c in cases if isinstance(c, dict) and c.get("prompt")]
    return DEFAULT_CASES


def repetition_ratio(text: str) -> float:
    """Share of the output taken up by its single most repeated non-trivial line."""
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 8]
    if len(lines) < 4:
        return 0.0
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    return max(counts.values()) / len(lines)


def check_response(
    case: dict[str, Any],
    text: str,
    finish_reason: str | None = None,
    reasoning_chars: int = 0,
) -> dict[str, Any]:
    """Deterministic scoring for one case. No second model involved."""
    failures: list[str] = []
    words = len([w for w in text.split() if w])

    min_words = int(case.get("min_words") or 0)
    if words < min_words:
        # A short answer because the budget ran out is a different fault from a
        # config that collapsed the output — say which, or the gate is unreadable.
        why = ""
        if finish_reason == "length":
            why = " — truncated at max_tokens"
            if reasoning_chars and not text.strip():
                why += f", the whole budget went to {reasoning_chars} chars of reasoning"
        failures.append(f"output is {words} words, expected at least {min_words}{why}")

    for pattern in case.get("must_match") or []:
        if not re.search(pattern, text, re.I):
            failures.append(f"missing expected pattern /{pattern}/")
    for pattern in case.get("must_not_match") or []:
        if re.search(pattern, text, re.I):
            failures.append(f"matched forbidden pattern /{pattern}/")

    ratio = repetition_ratio(text)
    if ratio > MAX_REPETITION_RATIO:
        failures.append(f"degenerate repetition ({ratio:.0%} of lines identical)")

    return {
        "id": case.get("id", "?"),
        "passed": not failures,
        "failures": failures,
        "words": words,
        "repetition_ratio": round(ratio, 3),
    }


def judge_response(
    judge_url: str, judge_model: str, prompt: str, answer: str, timeout: float = 120.0
) -> int | None:
    """Ask a reference model to grade an answer 1-5. None if the judge is unreachable."""
    import httpx

    body = {
        "model": judge_model,
        "messages": [
            {"role": "system", "content": JUDGE_RUBRIC},
            {"role": "user", "content": f"Question:\n{prompt}\n\nAnswer:\n{answer}\n\nScore:"},
        ],
        "max_tokens": 4,
        "temperature": 0,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{judge_url.rstrip('/')}/chat/completions", json=body)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("judge unreachable: %s", exc)
        return None
    text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    match = re.search(r"[1-5]", text)
    return int(match.group()) if match else None


def run_quality(
    port: int,
    model: str,
    *,
    cases: list[dict[str, Any]] | None = None,
    max_tokens: int = 512,
    judge_url: str = "",
    judge_model: str = "",
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Run the golden set against a cluster and return a pass rate."""
    from .measure import chat_once

    cases = cases or load_cases()
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            completion = chat_once(port, model, case["prompt"], "", max_tokens, timeout)
            text = completion.get("text") or ""
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "id": case.get("id", "?"),
                    "passed": False,
                    "failures": [f"request failed: {exc}"],
                    "words": 0,
                    "repetition_ratio": 0.0,
                }
            )
            continue
        result = check_response(
            case,
            text,
            completion.get("finish_reason"),
            int(completion.get("reasoning_chars") or 0),
        )
        result["finish_reason"] = completion.get("finish_reason")
        result["sample"] = text[:500]
        if judge_url and judge_model:
            result["judge_score"] = judge_response(judge_url, judge_model, case["prompt"], text)
        results.append(result)

    passed = sum(1 for r in results if r["passed"])
    scores = [r["judge_score"] for r in results if isinstance(r.get("judge_score"), int)]
    return {
        "cases": results,
        "passed": passed,
        "total": len(results),
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "judge_mean": round(sum(scores) / len(scores), 2) if scores else None,
    }
