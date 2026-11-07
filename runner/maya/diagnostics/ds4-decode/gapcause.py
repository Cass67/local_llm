# Classify idle gaps on one card: launch submitted late (queue ran dry), copy on the card during
# the gap, or kernel already queued (GPU-side wait). Also: what the late launcher thread was doing.
import bisect
import collections
import csv
import sys
from pathlib import Path

d, agent = Path(sys.argv[1]), sys.argv[2]
api = {r["Correlation_Id"]: r for r in csv.DictReader(open(next(d.glob("*hip_api_trace.csv"))))}
ks = sorted(
    (int(r["Start_Timestamp"]), int(r["End_Timestamp"]), r["Correlation_Id"], r["Thread_Id"])
    for r in csv.DictReader(open(next(d.glob("*kernel_trace.csv"))))
    if r["Agent_Id"] == agent
)
cps = sorted(
    (int(r["Start_Timestamp"]), int(r["End_Timestamp"]))
    for r in csv.DictReader(open(next(d.glob("*memory_copy_trace.csv"))))
    if agent in (r["Source_Agent_Id"], r["Destination_Agent_Id"])
)
calls = collections.defaultdict(list)  # per thread: sorted host API calls
for r in api.values():
    calls[r["Thread_Id"]].append(
        (int(r["Start_Timestamp"]), int(r["End_Timestamp"]), r["Function"])
    )
for v in calls.values():
    v.sort()
cls, late_doing, n = collections.Counter(), collections.Counter(), collections.Counter()
end = ks[0][1]
for s, e, cid, _th in ks[1:]:
    g = s - end
    if g > 0:
        a = api.get(cid)
        sub = int(a["End_Timestamp"]) if a else None
        cp = any(
            cs < s and ce > end
            for cs, ce in cps[
                max(0, bisect.bisect_left(cps, (end - 10**7, 0))) : bisect.bisect_left(cps, (s, 0))
            ]
        )
        if sub is None:
            k = "no api record"
        elif sub > end + 1000:
            k = "launch submitted after previous kernel ended (queue dry)"
        elif cp:
            k = "copy on this card during gap"
        else:
            k = "already queued: GPU-side wait"
        cls[k] += g
        n[k] += 1
        if k.startswith("launch") and a:
            # longest host call on the launcher thread inside the gap
            v = calls[a["Thread_Id"]]
            i = bisect.bisect_left(v, (end, 0, ""))
            best = max(
                (
                    (min(ce, s) - max(cs, end), f)
                    for cs, ce, f in v[max(0, i - 1) : bisect.bisect_left(v, (s, 0, ""))]
                ),
                default=(0, "none"),
            )
            late_doing[best[1] if best[0] > 0.3 * g else "between calls (engine code)"] += g
    end = max(end, e)
span = ks[-1][1] - ks[0][0]
print(f"{agent}: {len(ks)} kernels, idle {sum(cls.values()) / 1e6:.0f} ms of {span / 1e6:.0f} ms")
for k, v in cls.most_common():
    print(f"  {v / 1e6:6.0f} ms  {100 * v / span:4.1f}% of wall  n={n[k]:6d}  {k}")
print("  late launches: what the launcher thread was in during the gap")
for k, v in late_doing.most_common(6):
    print(f"    {v / 1e6:6.0f} ms  {k}")
