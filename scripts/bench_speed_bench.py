#!/usr/bin/env python3
"""Category-sliced speculative-decoding acceptance against an OpenAI-compatible server.

Prompts come from nvidia/SPEED-Bench (qualitative split): 80 prompts each for 11
semantic domains. Our own spec-decoding numbers were measured on hand-picked
code-echo prompts, which is the workload bias SPEED-Bench exists to expose --
acceptance on code echo says nothing about acceptance on prose or multilingual.

Reads draft_n / draft_n_accepted straight out of llama-server's `timings`, so no
metrics scraping is needed. Talks to an already-running server; it never starts
or stops one.

Prompts are fetched from the HF rows API and cached locally. They are not vendored
into the repo: the NVIDIA Evaluation Dataset License covers evaluation use, not
redistribution.

That same licensing is why 494 of the 880 rows ship as the literal placeholder
string below rather than real text -- NVIDIA cannot redistribute the source
datasets. Benchmarking a placeholder is worse than useless: the model rambles,
the n-gram drafter predicts its own rambling, and you measure ~100% acceptance
that means nothing. They are dropped here, loudly. Run NVIDIA's prepare.py to
hydrate them from the original sources and pass the result via --prompts-jsonl:

    base=https://raw.githubusercontent.com/NVIDIA-NeMo/Skills/refs/heads/main
    curl -LsSf $base/nemo_skills/dataset/speed-bench/prepare.py \
      | python3 - --output_dir ./speed-bench
"""

import argparse
import collections
import json
import pathlib
import statistics
import urllib.error
import urllib.request

ROWS_API = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=nvidia%2FSPEED-Bench&config=qualitative&split=test"
)
TOTAL_ROWS = 880
PLACEHOLDER = "SHOULD BE FETCHED FROM THE SOURCE"


def fetch_rows(cache: str) -> list[dict]:
    try:
        with open(cache) as fh:
            return json.load(fh)
    except FileNotFoundError:
        pass
    rows = []
    for off in range(0, TOTAL_ROWS, 100):
        with urllib.request.urlopen(  # noqa: S310 # nosec: B310
            f"{ROWS_API}&offset={off}&length=100", timeout=60
        ) as fh:
            rows += [r["row"] for r in json.load(fh)["rows"]]
    with open(cache, "w") as fh:
        json.dump(rows, fh)
    return rows


def load_prompts(cache: str, jsonl_dir: str) -> list[dict]:
    if jsonl_dir:
        rows = []
        src = pathlib.Path(jsonl_dir)
        paths = [src] if src.is_file() else sorted(src.glob("*.jsonl"))
        for path in paths:
            with open(path) as fh:
                rows += [json.loads(line) for line in fh if line.strip()]
        # prepare.py emits chat-format `messages` (all user-role) rather than `turns`
        for r in rows:
            if "turns" not in r:
                r["turns"] = [m["content"] for m in r["messages"] if m["role"] == "user"]
    else:
        rows = fetch_rows(cache)

    keep = [r for r in rows if not any(PLACEHOLDER in (t or "") for t in r["turns"])]
    dropped = len(rows) - len(keep)
    if dropped:
        per_cat = collections.Counter(
            r["category"] for r in rows if any(PLACEHOLDER in (t or "") for t in r["turns"])
        )
        print(
            f"WARNING: dropped {dropped}/{len(rows)} un-hydrated placeholder prompts "
            f"({', '.join(f'{c}={n}' for c, n in sorted(per_cat.items()))}).\n"
            "         Run NVIDIA's prepare.py and pass --prompts-jsonl for full coverage.",
            flush=True,
        )
    return keep


def chat(args, messages: list[dict]) -> dict:
    body = json.dumps(
        {
            "model": args.model,
            "messages": messages,
            "max_tokens": args.max_tokens,
            "temperature": args.temp,
            "cache_prompt": False,
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310 # nosec: B310
        f"{args.url}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=args.timeout) as fh:  # noqa: S310 # nosec: B310
        return json.load(fh)


def run_row(args, cat: str, row: dict) -> list | None:
    """Run one SPEED-Bench item (all its turns) and return a result row."""
    messages: list[dict] = []
    agg = {"prompt_n": 0, "predicted_n": 0, "draft_n": 0, "draft_n_accepted": 0}
    speeds = []
    for turn in row["turns"]:
        messages.append({"role": "user", "content": turn})
        try:
            payload = chat(args, messages)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            print(f"  {cat} {row['question_id'][:8]} FAILED: {exc}", flush=True)
            return None
        choice = payload["choices"][0]["message"]
        messages.append(
            {
                "role": "assistant",
                # reasoning models can return an empty content with the tokens
                # all in reasoning_content
                "content": choice.get("content") or choice.get("reasoning_content") or "",
            }
        )
        t = payload["timings"]
        for k in agg:
            agg[k] += t.get(k, 0)
        speeds.append(t["predicted_per_second"])

    draft_n = agg["draft_n"]
    accepted = agg["draft_n_accepted"]
    predicted = agg["predicted_n"]
    accept = 100.0 * accepted / draft_n if draft_n else 0.0
    cover = 100.0 * draft_n / predicted if predicted else 0.0
    tg = statistics.mean(speeds)
    print(
        f"  {cat:14s} {row['question_id'][:8]} "
        f"pred={predicted:4d} draft={draft_n:4d} acc={accepted:4d} "
        f"accept={accept:5.1f}% cover={cover:5.1f}% tg={tg:.2f}",
        flush=True,
    )
    return [
        cat,
        row["question_id"],
        int(bool(row["multiturn"])),
        agg["prompt_n"],
        predicted,
        draft_n,
        accepted,
        f"{accept:.1f}",
        f"{cover:.1f}",
        f"{tg:.2f}",
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8080")
    p.add_argument("--model", default="")
    p.add_argument("--per-category", type=int, default=10)
    p.add_argument("--categories", default="", help="comma-separated subset")
    p.add_argument("--max-tokens", type=int, default=256)
    # greedy by default: sampling noise swamps acceptance-rate differences
    p.add_argument("--temp", type=float, default=0.0)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--cache", default="speed-bench-qualitative.json")
    p.add_argument("--prompts-jsonl", default="", help="dir of prepare.py JSONL output")
    p.add_argument("--out", default="bench-speed-bench.tsv")
    args = p.parse_args()

    if not args.model:
        with urllib.request.urlopen(f"{args.url}/v1/models", timeout=30) as fh:  # noqa: S310
            args.model = json.load(fh)["data"][0]["id"]
        print(f"model: {args.model}", flush=True)

    rows = load_prompts(args.cache, args.prompts_jsonl)
    wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        if wanted and r["category"] not in wanted:
            continue
        by_cat.setdefault(r["category"], []).append(r)

    cols = [
        "category",
        "question_id",
        "multiturn",
        "prompt_n",
        "predicted_n",
        "draft_n",
        "draft_accepted",
        "accept_pct",
        "draft_cover_pct",
        "tg_tok_s",
    ]
    out_rows = []

    for cat in sorted(by_cat):
        for row in by_cat[cat][: args.per_category]:
            result = run_row(args, cat, row)
            if result is not None:
                out_rows.append(result)

    with open(args.out, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in out_rows:
            fh.write("\t".join(str(x) for x in r) + "\n")

    print("\n=== SUMMARY (by category) ===")
    print("category\tn\taccept_pct\tdraft_cover_pct\ttg_tok_s")
    tot_d = tot_a = 0
    for cat in sorted({r[0] for r in out_rows}):
        sel = [r for r in out_rows if r[0] == cat]
        d = sum(r[5] for r in sel)
        a = sum(r[6] for r in sel)
        tot_d += d
        tot_a += a
        cover = statistics.mean(float(r[8]) for r in sel)
        tg = statistics.mean(float(r[9]) for r in sel)
        acc = 100.0 * a / d if d else 0.0
        print(f"{cat}\t{len(sel)}\t{acc:.1f}\t{cover:.1f}\t{tg:.2f}")
    overall = 100.0 * tot_a / tot_d if tot_d else 0.0
    tg_all = statistics.mean(float(r[9]) for r in out_rows) if out_rows else 0.0
    print(f"ALL\t{len(out_rows)}\t{overall:.1f}\t-\t{tg_all:.2f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
