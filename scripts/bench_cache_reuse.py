#!/usr/bin/env python3
"""Measure KV prefix-cache reuse across agent turns vs --parallel.

Agents take turns round-robin (agent A turn 1, agent B turn 1, agent A turn 2, ...)
with no concurrency, so the only thing being measured is whether one agent's
prompt evicts another's cached prefix. With --parallel 1 there is a single slot,
so B's prompt should evict A's; with a slot per agent each keeps its own.
"""

import argparse
import json
import subprocess  # noqa: S404 # nosec: B404
import time
import urllib.error
import urllib.request

CONTAINER = "local-llm-bench-cache"


def build_context(agent: int, repeats: int) -> str:
    blocks = [
        f"Repository session {agent}. Review the following service code.\n",
    ]
    for i in range(repeats):
        blocks.append(
            f"class Handler{i}_a{agent}:\n"
            "    def __init__(self, pool, clock, retries=3):\n"
            "        self.pool = pool\n"
            "        self.clock = clock\n"
            "        self.retries = retries\n"
            "    def dispatch(self, req):\n"
            "        token = self.pool.acquire(req.tenant)\n"
            "        if token is None:\n"
            "            raise Backpressure(req.tenant)\n"
            "        return self._send(req, token, deadline=self.clock.now() + 30)\n\n"
        )
    return "".join(blocks)


TURN_PROMPTS = [
    "Summarise the retry semantics in two sentences.",
    "Now describe the backpressure behaviour in two sentences.",
    "Finally, name the biggest testing gap in two sentences.",
]


def docker_rm() -> None:
    subprocess.run(  # noqa: S603, S607 # nosec: B603, B607
        ["docker", "rm", "-f", CONTAINER],  # noqa: S607 # nosec: B607
        capture_output=True,
        check=False,
    )


def start_server(args, parallel: int) -> None:
    docker_rm()
    cmd = ["docker", "run", "-d", "--name", CONTAINER]
    cmd += args.docker_args.split()
    cmd += [args.docker_image, "llama-server"]
    cmd += ["-m", args.model, "--host", "127.0.0.1", "--port", str(args.port)]
    cmd += ["-ngl", "999", "-c", str(args.ctx), "-b", "4096", "-ub", "512"]
    cmd += ["--tensor-split", args.tensor_split, "--parallel", str(parallel)]
    cmd += ["--alias", args.alias, "--no-warmup"]
    cmd += args.extra_args.split()
    subprocess.run(cmd, capture_output=True, check=True)  # noqa: S603 # nosec: B603

    for _ in range(240):
        try:
            url = f"http://127.0.0.1:{args.port}/v1/models"
            with urllib.request.urlopen(url, timeout=5) as fh:  # noqa: S310 # nosec: B310
                if args.alias in fh.read().decode():
                    return
        except (urllib.error.URLError, OSError):
            pass
        state = subprocess.run(  # noqa: S603, S607 # nosec: B603, B607
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if state != "true":
            break
        time.sleep(2)
    logs = subprocess.run(  # noqa: S603, S607 # nosec: B603, B607
        ["docker", "logs", "--tail", "20", CONTAINER],  # noqa: S607 # nosec: B607
        capture_output=True,
        text=True,
        check=False,
    )
    raise SystemExit(
        f"server never became ready for parallel={parallel}\n{logs.stdout}{logs.stderr}"
    )


def chat(args, messages: list[dict]) -> tuple[dict, float]:
    body = json.dumps(
        {
            "model": args.alias,
            "messages": messages,
            "max_tokens": args.max_tokens,
            "temperature": 0,
            "cache_prompt": True,
        }
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{args.port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=900) as fh:  # noqa: S310 # nosec: B310
        payload = json.load(fh)
    return payload, (time.monotonic() - start) * 1000


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--alias", default="benchcache")
    p.add_argument("--docker-image", required=True)
    p.add_argument("--docker-args", default="")
    p.add_argument("--extra-args", default="")
    p.add_argument("--tensor-split", default="1,0.92")
    p.add_argument("--ctx", type=int, default=92160)
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--parallel", default="1,2,4")
    p.add_argument("--agents", type=int, default=2)
    p.add_argument("--turns", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=120)
    p.add_argument("--prompt-repeat", type=int, default=64)
    p.add_argument("--out", default="bench-cache-reuse.tsv")
    args = p.parse_args()

    cols = [
        "parallel",
        "agent",
        "turn",
        "prompt_n",
        "cache_n",
        "hit_pct",
        "ttft_ms",
        "e2e_ms",
        "tg_tok_s",
    ]
    rows = []
    summary = []

    try:
        for parallel in [int(x) for x in args.parallel.split(",")]:
            print(f"BOOT parallel={parallel}", flush=True)
            start_server(args, parallel)
            convos = {
                a: [
                    {
                        "role": "user",
                        "content": build_context(a, args.prompt_repeat) + "\n" + TURN_PROMPTS[0],
                    }
                ]
                for a in range(1, args.agents + 1)
            }
            wall_start = time.monotonic()
            for turn in range(1, args.turns + 1):
                for agent in range(1, args.agents + 1):
                    if turn > 1:
                        convos[agent].append(
                            {
                                "role": "user",
                                "content": TURN_PROMPTS[(turn - 1) % len(TURN_PROMPTS)],
                            }
                        )
                    payload, e2e = chat(args, convos[agent])
                    convos[agent].append(
                        {
                            "role": "assistant",
                            "content": payload["choices"][0]["message"]["content"],
                        }
                    )
                    t = payload["timings"]
                    usage = payload["usage"]
                    # usage is unambiguous: prompt_tokens is the whole prompt,
                    # cached_tokens the part served from KV cache. timings.prompt_n
                    # only counts tokens actually run through the model.
                    prompt_n = t["prompt_n"]
                    total = usage["prompt_tokens"]
                    cache_n = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                    hit = 100.0 * cache_n / total if total else 0.0
                    rows.append(
                        [
                            parallel,
                            agent,
                            turn,
                            prompt_n,
                            cache_n,
                            f"{hit:.1f}",
                            f"{t['prompt_ms']:.0f}",
                            f"{e2e:.0f}",
                            f"{t['predicted_per_second']:.2f}",
                        ]
                    )
                    print(
                        f"  p{parallel} agent{agent} turn{turn} "
                        f"prompt_n={prompt_n} cache_n={cache_n} hit={hit:.1f}% "
                        f"ttft={t['prompt_ms']:.0f}ms",
                        flush=True,
                    )
            wall = time.monotonic() - wall_start
            later = [r for r in rows if r[0] == parallel and r[2] > 1]
            mean_hit = sum(float(r[5]) for r in later) / len(later) if later else 0.0
            mean_ttft = sum(float(r[6]) for r in later) / len(later) if later else 0.0
            summary.append((parallel, wall, mean_hit, mean_ttft))
            print(
                f"DONE parallel={parallel} wall={wall:.1f}s "
                f"mean_hit_turns2plus={mean_hit:.1f}% mean_ttft_turns2plus={mean_ttft:.0f}ms",
                flush=True,
            )
    finally:
        docker_rm()

    with open(args.out, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")

    print("\n=== SUMMARY ===")
    print("parallel\twall_s\tmean_hit_turns2plus\tmean_ttft_turns2plus_ms")
    for parallel, wall, hit, ttft in summary:
        print(f"{parallel}\t{wall:.1f}\t{hit:.1f}%\t{ttft:.0f}")


if __name__ == "__main__":
    main()
