#!/usr/bin/env python3
"""Switch the live model and push its real limits into every agent config.

The server already knows the truth: /v1/models reports the context window and
output budget of whatever is actually running. Every client then re-declares
those numbers locally and silently wins over the server, so a profile change
has to be copied by hand into four or five files. This copies them instead.

    model-switch.py status                 # live runners vs what clients believe
    model-switch.py sync                   # rewrite client configs from /v1/models
    model-switch.py switch <family> [prof] # start it, then sync

Limits are synced; sampling is left alone. The runner launches with a single
sampler set, but a model with a thinking and a non-thinking mode wants two
different ones (Qwen wants temp 0.7 / top_p 0.80 / presence 1.5 non-thinking,
1.0 / 0.95 / 0 thinking), and only the client can vary that per request. So
per-variant sampling in the client is correct, not drift. Pass
--strip-sampling for a model that runs in one mode, where the profile should
own it outright.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404  # noqa: S404 — fixed argv, no shell
import sys
import urllib.request
from pathlib import Path

MGMT = os.environ.get("LOCAL_LLM_MGMT", "http://ubt26:3100")
ROUTER = os.environ.get("LOCAL_LLM_ROUTER", "http://ubt26:3200")
REPO = Path(__file__).resolve().parent.parent
AGENTS_DIR = Path(os.environ.get("AGENTS_CONFIG_DIR", Path.home() / ".config/local_llm/agents"))

# Only providers pointing at the router get rewritten; the same file often also
# holds cloud providers whose real limits we must not touch.
ROUTER_MARK = ":3200"

# Compaction headroom. NOT the output limit: that is a ceiling on one reply, while
# this is subtracted from the window on every turn, so setting it to a half-window
# output budget would halve the usable context. It only has to fit one tool loop --
# pi dies at 16384, and 49152 is the value that has held up.
RESERVE_FLOOR = 49152

SAMPLING_KEYS = {
    "temperature", "topP", "top_p", "topK", "top_k", "minP", "min_p",
    "presencePenalty", "presence_penalty", "frequencyPenalty", "frequency_penalty",
    "repetitionPenalty", "repetition_penalty", "repeatPenalty",
}  # fmt: skip


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as r:  # nosec B310  # noqa: S310
        return json.load(r)


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(  # noqa: S310 — fixed scheme
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as r:  # nosec B310  # noqa: S310
        return json.load(r)


def live_limits() -> tuple[int | None, int | None, list[dict]]:
    """Context/output the clients should use, plus the running models.

    The router may pick any running model, so the client's budget has to be the
    smallest one on offer — not the largest, or a long session dies on whichever
    model has the shorter window.
    """
    try:
        data = _get(f"{ROUTER}/v1/models")["data"]
    except OSError as exc:  # URLError subclasses OSError
        print(f"cannot reach the router at {ROUTER}: {exc}", file=sys.stderr)
        return None, None, []
    models = [m for m in data if m["id"] != "router"]
    ctxs = [m["context_window"] for m in models if m.get("context_window")]
    outs = [m["max_tokens"] for m in models if m.get("max_tokens")]
    return (min(ctxs) if ctxs else None), (min(outs) if outs else None), models


def reserve_for(ctx: int, out: int) -> int:
    return min(out, max(RESERVE_FLOOR, ctx // 8))


def _targets(seeds: bool = False) -> list[Path]:
    """Live client configs. The repo seeds under agents/ are opt-in: they only
    matter when bootstrapping a fresh host, and rewriting them here leaves the
    deploy host's checkout dirty, which aborts the next git pull."""
    paths = [
        Path.home() / ".config/opencode/opencode.json",
        AGENTS_DIR / "opencode/opencode.json",
        AGENTS_DIR / "opencode2/opencode.json",
        AGENTS_DIR / "pi/agent/models.json",
        AGENTS_DIR / "pi/agent/settings.json",
    ]
    if seeds:
        paths += [
            REPO / "agents/opencode.json",
            REPO / "agents/opencode2.json",
            REPO / "agents/pi-models.json",
            REPO / "agents/pi-settings.json",
        ]
    return [p for p in paths if p.exists()]


def _strip_sampling(obj: dict) -> list[str]:
    dropped = []
    for opts in [obj.get("options")] + list(obj.get("variants", {}).values()):
        if not isinstance(opts, dict):
            continue
        for k in list(opts):
            if k in SAMPLING_KEYS:
                del opts[k]
                dropped.append(k)
    return dropped


def _patch_model(m: dict, ctx: int, out: int, strip: bool) -> list[str]:
    """Set one model entry's limits. pi and opencode spell them differently."""
    changes: list[str] = []
    if "contextWindow" in m or "maxTokens" in m:  # pi shape
        pairs = [("contextWindow", ctx), ("maxTokens", out)]
        for key, want in pairs:
            if m.get(key) != want:
                changes.append(f"{key} {m.get(key)} -> {want}")
                m[key] = want
    else:  # opencode shape
        limit = m.setdefault("limit", {})
        for key, want in [("context", ctx), ("output", out)]:
            if limit.get(key) != want:
                changes.append(f"{key} {limit.get(key)} -> {want}")
                limit[key] = want
    dropped = _strip_sampling(m) if strip else []
    if dropped:
        changes.append(f"dropped client sampling {sorted(set(dropped))}")
    return changes


def patch_file(
    path: Path, ctx: int, out: int, write: bool = True, strip: bool = False
) -> list[str]:
    """Rewrite one config in place. Returns a list of human-readable changes."""
    data = json.loads(path.read_text())
    changes: list[str] = []

    # pi settings.json: no provider block, just the compaction reserve. It must
    # fit a whole tool loop or the turn clamps max_tokens to 1 and the session dies.
    # Keyed on the field existing, not on the file shape -- opencode configs also
    # carry a "compaction" block, spelled "reserved" and handled below.
    reserve = reserve_for(ctx, out)
    comp = data.get("compaction")
    if isinstance(comp, dict) and "reserveTokens" in comp and comp["reserveTokens"] != reserve:
        changes.append(f"reserveTokens {comp['reserveTokens']} -> {reserve}")
        comp["reserveTokens"] = reserve

    for key in ("provider", "providers"):
        for pid, prov in (data.get(key) or {}).items():
            settings = prov.get("options") or prov.get("settings") or prov
            base = str(settings.get("baseURL") or settings.get("baseUrl") or "")
            if ROUTER_MARK not in base:
                continue

            models = prov.get("models")
            # opencode: {id: model}. pi: [model, ...].
            entries = models.values() if isinstance(models, dict) else (models or [])
            for m in entries:
                if isinstance(m, dict):
                    changes += [f"{pid}: {c}" for c in _patch_model(m, ctx, out, strip)]

            # opencode's own compaction reserve lives at the top level.
            comp = data.get("compaction")
            if isinstance(comp, dict) and "reserved" in comp and comp["reserved"] != reserve:
                changes.append(f"reserved {comp.get('reserved')} -> {reserve}")
                comp["reserved"] = reserve

    if changes and write:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return changes


def cmd_sync(args) -> int:
    ctx, out, models = live_limits()
    if not ctx or not out:
        print("no running model advertises a context window — start one first", file=sys.stderr)
        return 1
    print(f"live: {', '.join(m['id'] for m in models)}  ctx={ctx} output={out}\n")
    for path in _targets(args.seeds):
        changes = patch_file(path, ctx, out, write=not args.dry_run, strip=args.strip_sampling)
        label = str(path).replace(str(Path.home()), "~")
        print(f"{label}\n  " + ("\n  ".join(changes) if changes else "up to date"))
    if args.dry_run:
        print("\n(dry run — nothing written)")
    else:
        print("\nrestart the agents to pick these up")
    return 0


def cmd_status(args) -> int:
    ctx, out, models = live_limits()
    if not models:
        return 1
    print(f"{'ADVERTISED':<12} ctx={ctx} output={out}")
    for m in models:
        print(f"  {m['id']}  ctx={m.get('context_window')} max_tokens={m.get('max_tokens')}")

    active = _get(f"{MGMT}/api/clusters")["clusters"]
    print("\nRUNNING")
    for c in active:
        if c.get("active"):
            a = c["active"]
            print(f"  {c['name']:<14} {a.get('model')}  profile={a.get('profile')}")

    print("\nCLIENTS")
    for path in _targets(args.seeds):
        changes = patch_file(path, ctx or 0, out or 0, write=False, strip=False)
        label = str(path).replace(str(Path.home()), "~")
        print(f"  {label}: " + ("; ".join(changes) if changes else "in sync"))
    return 0


def cmd_switch(args) -> int:
    clusters = _get(f"{MGMT}/api/clusters")["clusters"]
    if args.cluster:
        match = [c for c in clusters if args.cluster in (c["name"], c["id"])]
    else:
        match = [c for c in clusters if c.get("active")] or clusters
    if len(match) != 1:
        names = ", ".join(c["name"] for c in match)
        print(f"pick one with --cluster: {names}", file=sys.stderr)
        return 1
    cluster = match[0]

    print(f"starting {args.family} ({args.profile or 'default profile'}) on {cluster['name']} ...")
    res = _post(
        f"{MGMT}/api/clusters/{cluster['id']}/start",
        {"family": args.family, "profile": args.profile or ""},
    )
    print(f"  {res.get('status')}: {res.get('model')}\n")

    ctx, _out, _models = live_limits()
    profile_ctx = _profile_context(args.family, args.profile)
    if profile_ctx and ctx and profile_ctx != ctx:
        print(
            f"!! server advertises ctx={ctx} but the profile says {profile_ctx} — "
            f"the accepted-model JSON pin is stale (mgmt needs the openai.py fix deployed)\n",
            file=sys.stderr,
        )

    if args.remote:
        subprocess.run(  # nosec B603 B607  # noqa: S603, S607
            [  # noqa: S607 — ssh resolved from PATH
                "ssh",
                args.remote,
                f"python3 {args.remote_repo}/scripts/model-switch.py sync",
            ],
            check=False,
        )
    return cmd_sync(args)


def _profile_context(family: str, profile: str) -> int | None:
    try:
        fam = _get(f"{MGMT}/api/profiles/{family}")
        name = profile or fam.get("default")
        return fam.get("profiles", {}).get(name, {}).get("context")
    except Exception:  # noqa: BLE001 — advisory check only
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="show changes without writing")
    ap.add_argument(
        "--seeds",
        action="store_true",
        help="also rewrite the repo agents/*.json seeds (dirties the checkout)",
    )
    ap.add_argument(
        "--strip-sampling",
        action="store_true",
        help="also delete client-side temp/top_p/penalties so the profile owns them",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("sync").set_defaults(func=cmd_sync)

    sw = sub.add_parser("switch")
    sw.add_argument("family")
    sw.add_argument("profile", nargs="?", default="")
    sw.add_argument("--cluster", default="", help="cluster name or id")
    sw.add_argument("--remote", default="", help="also sync agent configs on this ssh host")
    sw.add_argument("--remote-repo", default="~/git/local_llm")
    sw.set_defaults(func=cmd_switch)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
