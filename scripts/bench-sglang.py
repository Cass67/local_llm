#!/usr/bin/env python3
"""Decode/prefill benchmark for an sglang (or llama-server) OpenAI endpoint.

Prompts are randomised per request so the radix cache never serves them: a
repeated prompt returns in <1s and is not a decode measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CORPUS_GLOBS = (
    "container/backend/*.py",
    "scripts/*.py",
    "*.md",
)


def load_corpus(root: str) -> str:
    """Real text, not random words.

    A junk-word prompt makes the model emit degenerate output, speculation
    rejects every draft, and the measured decode rate is a property of the
    benchmark rather than the server (9 tok/s vs 40 on the same config).
    """
    import glob
    import os

    parts = []
    for pat in CORPUS_GLOBS:
        for path in sorted(glob.glob(os.path.join(root, pat))):
            try:
                parts.append(open(path, encoding="utf-8", errors="ignore").read())
            except OSError:
                continue
    text = "\n\n".join(parts)
    if len(text) < 200_000:
        raise SystemExit(f"corpus too small ({len(text)} chars) under {root}")
    return text


def slice_corpus(corpus: str, depth_tokens: int, rng: random.Random) -> str:
    # ~3.6 chars/token for mixed code+prose. A random offset keeps every
    # request a radix-cache miss without making the text unnatural.
    n_chars = max(400, int(depth_tokens * 3.6))
    off = rng.randrange(0, max(1, len(corpus) - n_chars))
    return corpus[off : off + n_chars]


def make_prompt(kind: str, depth_tokens: int, rng: random.Random, corpus: str) -> str:
    body = slice_corpus(corpus, depth_tokens, rng)
    if kind == "fresh":
        return (
            "Read the following source excerpt, then write a detailed design "
            "review of it in prose. Do not quote the code.\n\n" + body
        )
    if kind == "echo":
        # Edit-shaped: the answer is mostly a copy of the input. This is where
        # ngram/EAGLE speculation pays, so it must be its own category.
        return "Repeat the following text back verbatim, changing nothing:\n\n" + body
    raise SystemExit(f"unknown prompt kind {kind}")


def one_request(url: str, model: str, prompt: str, max_tokens: int, timeout: int) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "ignore_eos": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(  # noqa: S310
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    ttft = None
    n_chunks = 0
    usage = {}
    # Fixed http(s) benchmark endpoint on the LAN; no user-supplied scheme.
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            obj = json.loads(payload)
            if obj.get("usage"):
                usage = obj["usage"]
            choices = obj.get("choices") or []
            if choices and (choices[0].get("delta") or {}).get("content"):
                if ttft is None:
                    ttft = time.perf_counter() - t0
                n_chunks += 1
    total = time.perf_counter() - t0
    out_tok = usage.get("completion_tokens") or n_chunks
    in_tok = usage.get("prompt_tokens") or 0
    ttft = ttft if ttft is not None else total
    decode_s = max(total - ttft, 1e-6)
    return {
        "ttft": ttft,
        "total": total,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "prefill_tps": in_tok / ttft if ttft > 0 else 0.0,
        "decode_tps": (out_tok - 1) / decode_s if out_tok > 1 else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8086")
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--kind", default="fresh", choices=["fresh", "echo"])
    ap.add_argument("--depth", type=int, default=2048, help="approx prompt tokens")
    ap.add_argument("--out", type=int, default=256, help="max output tokens")
    ap.add_argument("--conc", type=int, default=1)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--label", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--corpus-root", default="/home/cass/git/local_llm")
    args = ap.parse_args()

    rng = random.Random()  # noqa: S311  # nosec B311 - picks corpus offsets, not secrets
    corpus = load_corpus(args.corpus_root)
    results = []
    for _ in range(args.reps):
        prompts = [make_prompt(args.kind, args.depth, rng, corpus) for _ in range(args.conc)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.conc) as pool:
            batch = list(
                pool.map(
                    lambda p: one_request(args.url, args.model, p, args.out, args.timeout),
                    prompts,
                )
            )
        wall = time.perf_counter() - t0
        results.append({"wall": wall, "reqs": batch})

    flat = [r for rep in results for r in rep["reqs"]]
    agg = {
        "label": args.label,
        "kind": args.kind,
        "depth": args.depth,
        "out": args.out,
        "conc": args.conc,
        "reps": args.reps,
        "in_tok": int(statistics.median(r["in_tok"] for r in flat)),
        "out_tok": int(statistics.median(r["out_tok"] for r in flat)),
        "ttft_s": round(statistics.median(r["ttft"] for r in flat), 3),
        "prefill_tps": round(statistics.median(r["prefill_tps"] for r in flat), 1),
        "decode_tps": round(statistics.median(r["decode_tps"] for r in flat), 2),
        "decode_tps_max": round(max(r["decode_tps"] for r in flat), 2),
        "agg_out_tps": round(
            sum(r["out_tok"] for rep in results for r in rep["reqs"])
            / sum(rep["wall"] for rep in results),
            2,
        ),
    }
    if args.json:
        print(json.dumps(agg))
    else:
        print(
            f"{agg['label'] or args.kind:<22} depth={agg['in_tok']:>6} conc={args.conc} "
            f"ttft={agg['ttft_s']:>6}s prefill={agg['prefill_tps']:>7}/s "
            f"decode={agg['decode_tps']:>6}/s agg={agg['agg_out_tps']:>7}/s"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
