#!/usr/bin/env python3
"""A/B one OpenAI-compatible endpoint on speed, accuracy and long context; rows to JSONL.

    bench_ab_api.py --url http://127.0.0.1:8088/v1 --label strata --out ab-strata.jsonl \
        --data ~/scratch/ab --haystack DIR [DIR ...] [--suites niah,gsm8k,humaneval,tools]

Every request starts with a unique nonce so no server can reuse a cached prefix. Greedy
(temperature 0), thinking off. Speed comes from the server's own `timings` block (llama-server
and Strata both return it). Run once per model on the same box, then --summary a.jsonl b.jsonl.
"""

# S311 seeded haystacks/needles, S310 local endpoint, S404/S603 HumanEval runs the model's code
# ruff: noqa: S311, S310, S404, S603
import argparse
import gzip
import json
import random
import re
import subprocess  # nosec B404
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

NIAH_DEPTHS = (16_000, 64_000, 120_000)  # approximate prompt tokens
NIAH_POSITIONS = (0.1, 0.5, 0.9)
CHARS_PER_TOKEN = 3.4  # mixed code/prose under the Qwen tokenizer; prompt_n reports the real count


def chat(url: str, messages: list, max_tokens: int, tools: list | None = None) -> dict:
    body = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        f"{url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=3600) as r:  # nosec B310
        resp = json.load(r)
    resp["_wall_s"] = time.monotonic() - t0
    return resp


def speed(resp: dict) -> dict:
    t = resp.get("timings") or {}
    acc = (t.get("draft_n_accepted") or 0) / t["draft_n"] if t.get("draft_n") else None
    return {
        "prompt_n": t.get("prompt_n"),
        "prefill_tps": t.get("prompt_per_second"),
        "decode_tps": t.get("predicted_per_second"),
        "gen_n": t.get("predicted_n"),
        "draft_accept": acc,
        "wall_s": round(resp["_wall_s"], 2),
    }


def text_of(resp: dict) -> str:
    return resp["choices"][0]["message"].get("content") or ""


def haystack(dirs: list[str], chars: int, seed: int) -> str:
    files = sorted(
        p
        for d in dirs
        for p in Path(d).rglob("*")
        if p.suffix in {".md", ".cpp", ".cu", ".py", ".hpp"}
    )
    random.Random(seed).shuffle(files)
    out, n = [], 0
    for p in files:
        t = p.read_text(errors="replace")
        out.append(f"\n\n===== {p.name} =====\n{t}")
        n += len(t)
        if n >= chars:
            break
    return "".join(out)[:chars]


def run_niah(a, emit):
    for depth in NIAH_DEPTHS:
        for pos in NIAH_POSITIONS:
            rng = random.Random(depth * 10 + int(pos * 10))
            keys = {
                f"project {w}": f"{rng.randrange(100000, 999999)}"
                for w in ("amber", "basalt", "cobalt", "dune")
            }
            target = rng.choice(sorted(keys))
            hay = haystack(a.haystack, int(depth * CHARS_PER_TOKEN), seed=depth)
            # the target needle at `pos`, the three distractors at random depths
            needles = [(pos, target)] + [(rng.random(), k) for k in sorted(keys) if k != target]
            for at, k in sorted(needles, reverse=True):  # back to front: earlier offsets stay valid
                i = hay.rfind("\n", 0, int(len(hay) * at)) + 1
                hay = hay[:i] + f"The access code for {k} is {keys[k]}.\n" + hay[i:]
            q = (
                f"[{uuid.uuid4()}]\n{hay}\n\n"
                f"First line of your answer: the access code for {target}, digits only. "
                "Then summarize the document above in about 200 words."
            )
            resp = chat(a.url, [{"role": "user", "content": q}], 320)
            out = text_of(resp)
            first = out.strip().splitlines()[0] if out.strip() else ""
            emit(
                {
                    "suite": "niah",
                    "depth": depth,
                    "pos": pos,
                    "ok": keys[target] in first,
                    "want": keys[target],
                    "got": first[:80],
                    **speed(resp),
                }
            )


def run_gsm8k(a, emit):
    rows = [
        json.loads(line) for line in (Path(a.data) / "gsm8k_test.jsonl").read_text().splitlines()
    ][: a.gsm8k_n]
    for i, r in enumerate(rows):
        want = r["answer"].split("####")[-1].strip().replace(",", "")
        q = (
            f"[{uuid.uuid4()}]\n{r['question']}\n"
            "Solve it step by step, then end with a line 'ANSWER: <number>'."
        )
        resp = chat(a.url, [{"role": "user", "content": q}], 1024)
        m = re.findall(r"ANSWER:\s*\$?(-?[\d,]*\.?\d+)", text_of(resp))
        got = m[-1].replace(",", "").rstrip(".") if m else ""
        ok = got != "" and abs(float(got) - float(want)) < 1e-6
        emit({"suite": "gsm8k", "i": i, "ok": ok, "want": want, "got": got, **speed(resp)})


def run_humaneval(a, emit):
    with gzip.open(Path(a.data) / "HumanEval.jsonl.gz", "rt") as f:
        rows = [json.loads(line) for line in f]
    for r in rows:
        q = (
            f"[{uuid.uuid4()}]\nComplete this Python function. Reply with the full function in one "
            f"```python code block, nothing else.\n\n```python\n{r['prompt']}```"
        )
        resp = chat(a.url, [{"role": "user", "content": q}], 1024)
        blocks = re.findall(r"```(?:python)?\n(.*?)```", text_of(resp), re.S)
        code = blocks[0] if blocks else text_of(resp)
        prog = f"{r['prompt']}\n{code}\n\n{r['test']}\ncheck({r['entry_point']})\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(prog)
        try:
            ok = (
                subprocess.run([sys.executable, f.name], capture_output=True, timeout=20).returncode
                == 0
            )  # nosec B603
        except subprocess.TimeoutExpired:
            ok = False
        Path(f.name).unlink()
        emit({"suite": "humaneval", "task": r["task_id"], "ok": ok, **speed(resp)})


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]
TOOL_CASES = [
    ("What's the weather in Lisbon right now?", "get_weather", "city", "lisbon"),
    ("Open src/main.py and show me what it does.", "read_file", "path", "src/main.py"),
    ("Is it raining in Osaka?", "get_weather", "city", "osaka"),
    ("Read the README.md file please.", "read_file", "path", "readme.md"),
    ("I need the contents of config/app.yaml", "read_file", "path", "config/app.yaml"),
    ("How cold is it in Reykjavik today?", "get_weather", "city", "reykjavik"),
]


def run_tools(a, emit):
    for prompt, fn, arg, val in TOOL_CASES:
        resp = chat(a.url, [{"role": "user", "content": f"[{uuid.uuid4()}] {prompt}"}], 512, TOOLS)
        calls = resp["choices"][0]["message"].get("tool_calls") or []
        ok = False
        if calls:
            c = calls[0]["function"]
            try:
                ok = c["name"] == fn and val in str(json.loads(c["arguments"]).get(arg, "")).lower()
            except (json.JSONDecodeError, AttributeError):
                ok = False
        emit({"suite": "tools", "fn": fn, "ok": ok, "calls": len(calls), **speed(resp)})


def summary(paths: list[str]) -> None:
    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        return xs[len(xs) // 2] if xs else None

    for p in paths:
        rows = [json.loads(line) for line in Path(p).read_text().splitlines()]
        label = rows[0]["label"] if rows else p
        print(f"== {label}")
        for s in ("gsm8k", "humaneval", "tools"):
            r = [x for x in rows if x["suite"] == s]
            if r:
                ok = sum(x["ok"] for x in r)
                print(f"  {s:10s} {ok}/{len(r)}  decode med {med([x['decode_tps'] for x in r])}")
        for d in NIAH_DEPTHS:
            r = [x for x in rows if x["suite"] == "niah" and x["depth"] == d]
            if r:
                ok, pn = sum(x["ok"] for x in r), med([x["prompt_n"] for x in r])
                pre, dec = med([x["prefill_tps"] for x in r]), med([x["decode_tps"] for x in r])
                print(
                    f"  niah {d // 1000:>3}K {ok}/{len(r)} prompt_n~{pn} prefill {pre} decode {dec}"
                )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--label")
    ap.add_argument("--out")
    ap.add_argument("--data", default=str(Path.home() / "scratch/ab"))
    ap.add_argument("--haystack", nargs="+", default=[])
    ap.add_argument("--suites", default="tools,gsm8k,humaneval,niah")
    ap.add_argument("--gsm8k-n", type=int, default=100)
    ap.add_argument("--summary", nargs="+")
    a = ap.parse_args()
    if a.summary:
        return summary(a.summary)
    out = open(a.out, "a")  # noqa: SIM115 - one handle for the whole run

    def emit(row):
        row = {"label": a.label, **row}
        out.write(json.dumps(row) + "\n")
        out.flush()
        print(json.dumps(row), flush=True)

    suites = {"niah": run_niah, "gsm8k": run_gsm8k, "humaneval": run_humaneval, "tools": run_tools}
    for s in a.suites.split(","):
        suites[s](a, emit)


if __name__ == "__main__":
    main()
