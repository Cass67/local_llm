import subprocess, time, pathlib, glob, json, threading, sys  # nosec B404

root = pathlib.Path("/mnt/scratch/maya-841")
mode = sys.argv[1]
queues = sys.argv[2] if len(sys.argv) > 2 else None
if queues == "-":
    queues = None
exe = sys.argv[3] if len(sys.argv) > 3 else "/work/maya-841/queues"
name = "micro-" + mode + ("-q" + queues if queues else "")
cmd = ["docker", "exec"]
if queues:
    cmd += ["-e", "GPU_MAX_HW_QUEUES=" + queues]
cmd += ["maya-841-debug", exe, mode]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # nosec B603 B607
start = time.monotonic()


def log():
    for s in p.stdout:
        print(round(time.monotonic() - start, 1), s.strip(), flush=True)


threading.Thread(target=log, daemon=True).start()


def read(p):
    try:
        return int(pathlib.Path(p).read_text().strip())
    except:
        return None


with open(root / (name + ".jsonl"), "w") as f:
    while p.poll() is None:
        g = []
        for d in sorted(glob.glob("/sys/class/drm/card[0-9]/device")):
            h = glob.glob(d + "/hwmon/hwmon*")[0]
            g.append([read(d + "/gpu_busy_percent"), read(h + "/power1_average")])
        row = {"t": round(time.monotonic() - start, 1), "gpus": g}
        f.write(json.dumps(row) + "\n")
        f.flush()
        print(json.dumps(row), flush=True)
        time.sleep(2)
print("exit", p.returncode, flush=True)
