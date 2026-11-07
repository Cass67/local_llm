#!/usr/bin/env python3
"""Run a GPU microbench with telemetry on the GPU host. Refuses to start if GPUs are in use.

run.py [--container NAME] NAME -- CMD...
Writes results/<kernel>-<NAME>.jsonl and prints per-stage busy, watts and KFD queues per card.
"""

import argparse
import collections
import glob
import json
import pathlib
import platform
import statistics
import subprocess  # noqa: S404  # nosec B404
import threading
import time

BUSY_LIMIT = 5


def read_int(path):
    try:
        return int(pathlib.Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def sample_gpus():
    gpus = {}
    for dev in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        hwmon = glob.glob(dev + "/hwmon/hwmon*")
        busy = read_int(dev + "/gpu_busy_percent")
        if busy is None or not hwmon:
            continue
        power = read_int(hwmon[0] + "/power1_average")
        gpus[dev.split("/")[4]] = {"busy": busy, "watts": power / 1e6 if power else None}
    return gpus


def kfd_queues():
    return {
        d.rsplit("/", 1)[1]: len(glob.glob(d + "/queues/[0-9]*"))
        for d in glob.glob("/sys/class/kfd/kfd/proc/[0-9]*")
    }


def summarize(rows):
    stages = collections.defaultdict(lambda: collections.defaultdict(list))
    queues = collections.Counter()
    for row in rows:
        queues[row["stage"]] = max(queues[row["stage"]], sum(row["queues"].values()))
        for card, gpu in row["gpus"].items():
            stages[row["stage"]][card].append(gpu)
    for stage, cards in stages.items():
        parts = []
        for card, gpus in sorted(cards.items()):
            watts = [g["watts"] for g in gpus if g["watts"] is not None]
            busy = statistics.median(g["busy"] for g in gpus)
            parts.append(f"{card} {busy:.0f}%/{statistics.median(watts) if watts else 0:.0f}W")
        print(f"{stage[:40]:40} q={queues[stage]:<3} " + " ".join(parts))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container")
    parser.add_argument("name")
    parser.add_argument("cmd", nargs="+")
    args = parser.parse_args()

    # A container held open with `sleep` has KFD access only once a program opens it, so any
    # KFD process or busy card means someone else is using the GPUs.
    if holders := kfd_queues():
        raise SystemExit(f"refusing: KFD processes active: {sorted(holders)}")
    if busy := {c: g["busy"] for c, g in sample_gpus().items() if g["busy"] > BUSY_LIMIT}:
        raise SystemExit(f"refusing: cards busy: {busy}")

    cmd = (["docker", "exec", args.container] if args.container else []) + args.cmd
    out = pathlib.Path(__file__).parent / "results" / f"{platform.release()}-{args.name}.jsonl"
    out.parent.mkdir(exist_ok=True)

    stage = "starting"
    start = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # noqa: S603  # nosec B603

    def reader():
        nonlocal stage
        for line in proc.stdout:
            line = line.strip()
            print(f"{time.monotonic() - start:7.1f} {line}", flush=True)
            if not line.startswith("{"):
                stage = line.split(" pid=")[0]
            else:
                with results_lock:
                    results.write(json.dumps({"result": json.loads(line)}) + "\n")

    rows = []
    results_lock = threading.Lock()
    with out.open("w") as results:
        thread = threading.Thread(target=reader)
        thread.start()
        while proc.poll() is None:
            row = {
                "t": round(time.monotonic() - start, 2),
                "stage": stage,
                "queues": kfd_queues(),
                "gpus": sample_gpus(),
            }
            rows.append(row)
            with results_lock:
                results.write(json.dumps(row) + "\n")
                results.flush()
            time.sleep(0.5)
        thread.join()
    summarize(rows)
    print(f"exit {proc.returncode}, wrote {out}")
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
