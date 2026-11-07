#!/usr/bin/env python3
"""Critical-path reports for a rocprofv3 kernel trace of maya-ds4 decode (--tp 4).

trace.py DIR    DIR holds the *kernel_trace.csv from `rocprofv3 --attach ... --kernel-trace`.
Prints: wall by how many cards do real work, allreduce wait per card, the lead's idle gaps by
neighbouring kernels, and the kernels the lead runs that the others do not.
"""

import collections
import csv
import re
import sys
from pathlib import Path

SPIN = ("mx_wait_kernel", "wait_seq_kernel", "xfer_get_kernel")
AR = "ar_rs16_kernel"


def short(name):
    name = re.sub(r"\(.*", "", name.replace("(anonymous namespace)::", ""))
    return name.split("::")[-1]


def load(path):
    rows = csv.DictReader(open(next(Path(path).rglob("*kernel_trace.csv"))))
    return [
        (r["Agent_Id"], int(r["Start_Timestamp"]), int(r["End_Timestamp"]), short(r["Kernel_Name"]))
        for r in rows
    ]


def coverage(ks):
    t0, t1 = min(k[1] for k in ks), max(k[2] for k in ks)
    ev = sorted(e for a, s, t, n in ks if n not in SPIN for e in ((s, 1, a), (t, -1, a)))
    per, cover, last = collections.Counter(), collections.Counter(), t0
    for t, d, a in ev:
        cover[sum(v > 0 for v in per.values())] += t - last
        last = t
        per[a] += d
    cover[0] += t1 - last
    print(
        f"window {(t1 - t0) / 1e6:.0f} ms; wall by cards doing real work (spin kernels excluded):"
    )
    for n in range(5):
        print(f"  {n} cards: {100 * cover[n] / (t1 - t0):5.1f}%")


def allreduce(ks):
    ar, comp = collections.defaultdict(list), collections.Counter()
    for a, s, t, n in ks:
        if n == AR:
            ar[a].append((t - s) / 1e3)
        elif n not in SPIN:
            comp[a] += (t - s) / 1e3
    print(f"{AR} per card (us), and compute without allreduce or spin kernels:")
    for a in sorted(ar):
        v = sorted(ar[a])
        p05, p50, p90 = (v[int(p * (len(v) - 1))] for p in (0.05, 0.5, 0.9))
        print(
            f"  {a}: n={len(v)} p05={p05:.0f} p50={p50:.0f} p90={p90:.0f} "
            f"total={sum(v) / 1e3:.0f} ms compute={comp[a] / 1e3:.0f} ms"
        )


def gaps(ks, agent):
    ev = sorted((s, t, n) for a, s, t, n in ks if a == agent)
    pairs, small, total = collections.Counter(), 0, 0
    end, prev = ev[0][1], ev[0][2]
    for s, t, n in ev[1:]:
        g = (s - end) / 1e3
        if g > 0:
            total += g
            small += g if g < 50 else 0
            if g > 25:
                pairs[(prev, n)] += g
        if t > end:
            end, prev = t, n
    print(
        f"{agent} idle {total / 1e3:.0f} ms, {small / 1e3:.0f} ms of it in gaps under 50 us; top:"
    )
    for (a, b), v in pairs.most_common(6):
        print(f"  {v / 1e3:5.0f} ms  {a} -> {b}")


def lead_only(ks, lead, others):
    cnt = collections.defaultdict(collections.Counter)
    for a, _, _, n in ks:
        cnt[a][n] += 1
    print(f"kernels {lead} runs more than the others (counts: lead / others):")
    top = sorted(cnt[lead], key=lambda k: min(cnt[a][k] for a in others) - cnt[lead][k])[:8]
    for k in top:
        print(f"  {k[:40]:40} {cnt[lead][k]:6d} / " + " ".join(str(cnt[a][k]) for a in others))


def main():
    ks = load(sys.argv[1])
    agents = sorted({k[0] for k in ks})
    coverage(ks)
    allreduce(ks)
    gaps(ks, agents[0])
    lead_only(ks, agents[0], agents[1:])


if __name__ == "__main__":
    main()
