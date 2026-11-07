#!/usr/bin/env python3
"""A/B one maya_env change on the live DS4 profile. Run on ubt26.

arm.py TAG [KEY=VAL ...]   back up the profile once, add the env, restart the runner, run
                           ~/scratch/ds4-ab/pair.py TAG, then a 3 s rocprofv3 trace into TAG-trace/
arm.py --restore           put the backed-up profile back, restart, delete the backup
Tracing needs ROCP_TOOL_ATTACH=1 among the env.
"""

import json
import pathlib
import shutil
import subprocess  # noqa: S404  # nosec B404
import sys
import threading
import time
import urllib.request

FAM, PROF, CLUSTER = "maya-dsv41-q4xl-huihui", "default", "0663b08f"
RUNNER = "local-llm-runner-cluster-7900s-maya-0663b08f"
STATE = pathlib.Path.home() / ".local/share/local_llm/profiles.json"
BACKUP = STATE.with_name("profiles.json.bak-arm")
PAIR = pathlib.Path.home() / "scratch/ds4-ab"
HERE = pathlib.Path(__file__).parent


def http(method, url, body=None, timeout=900):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"}
    r = urllib.request.Request(url, data, hdr, method=method)  # noqa: S310  # nosec B310
    try:
        return json.load(urllib.request.urlopen(r, timeout=timeout))  # noqa: S310  # nosec B310  # nosemgrep
    except (OSError, ValueError) as e:  # start can time out before DS4 loads; health decides
        return {"error": str(e)}


def run(*cmd):
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603  # nosec B603
    return out.stdout.strip()


def restart_with(profile):
    run("docker", "stop", "-t", "30", RUNNER)
    put = http("PUT", f"http://localhost:3100/api/profiles/{FAM}/{PROF}", profile)
    print(
        "put:", put.get("status"), put.get("restarted_clusters"), put.get("error", ""), flush=True
    )
    start = http("POST", f"http://localhost:3100/api/clusters/{CLUSTER}/start", {"family": FAM})
    print("start:", start.get("status"), start.get("error", ""), flush=True)
    t0 = time.time()
    while http("GET", "http://localhost:8088/health", timeout=3).get("status") != "ok":
        if time.time() - t0 > 900:
            sys.exit("runner not healthy after 900 s")
        time.sleep(10)
    fmt = "restarts={{.RestartCount}} image={{.Image}}"
    print(
        f"healthy after {time.time() - t0:.0f}s;", run("docker", "inspect", RUNNER, "--format", fmt)
    )


def trace(tag):
    sys.path.insert(0, str(PAIR))
    import pair

    pid = run("docker", "exec", RUNNER, "pgrep", "-f", "engine/maya-ds4").split()[0]
    req = threading.Thread(target=pair.req, args=(pair.PROMPTS["story"],))
    req.start()
    time.sleep(10)
    prof = "/opt/rocm/bin/rocprofv3"
    args = f"--attach {pid} --attach-duration-msec 3000 --kernel-trace --output-format csv"
    out = "/tmp/rp"  # noqa: S108  # nosec B108
    run("docker", "exec", RUNNER, "rm", "-rf", out)
    run("docker", "exec", "--privileged", RUNNER, "sh", "-c", f"{prof} {args} -d {out} -o t")
    # the engine writes the trace after detach, up to a minute or two later
    for _ in range(60):
        if run("docker", "exec", RUNNER, "sh", "-c", f"ls {out}/*kernel_trace.csv 2>/dev/null"):
            break
        time.sleep(3)
    req.join()
    dst = HERE / f"{tag}-trace"
    shutil.rmtree(dst, ignore_errors=True)
    run("docker", "cp", f"{RUNNER}:{out}", str(dst))
    print("trace:", sorted(p.name for p in dst.glob("*.csv")), flush=True)


def main():
    if sys.argv[1] == "--restore":
        restart_with(json.loads(BACKUP.read_text())["families"][FAM]["profiles"][PROF])
        BACKUP.unlink()
        return
    if not BACKUP.exists():
        shutil.copy2(STATE, BACKUP)
    profile = json.loads(BACKUP.read_text())["families"][FAM]["profiles"][PROF]
    tag, extra = sys.argv[1], dict(a.split("=", 1) for a in sys.argv[2:])
    profile.setdefault("maya_env", {}).update(extra)
    print(f"== arm {tag}: extra env {extra}", flush=True)
    restart_with(profile)
    time.sleep(10)
    subprocess.run([sys.executable, str(PAIR / "pair.py"), tag], check=False)  # noqa: S603  # nosec B603
    if extra.get("ROCP_TOOL_ATTACH") == "1":
        trace(tag)


if __name__ == "__main__":
    main()
