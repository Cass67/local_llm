import subprocess, time, pathlib, glob, json, threading, sys, collections  # nosec B404

root = pathlib.Path("/mnt/scratch/maya-841")
name = sys.argv[1]
clean = sys.argv[2]
high = sys.argv[3]
normal = sys.argv[4]
cap = sys.argv[5] if len(sys.argv) > 5 else None
cmd = ["docker", "exec"]
if cap:
    cmd += ["-e", "GPU_MAX_HW_QUEUES=" + cap]
cmd += ["maya-841-debug", "/work/maya-841/queue-steps", clean, high, normal]
start = time.monotonic()
stage = "starting"
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # nosec B603 B607


def reader():
    global stage
    for s in p.stdout:
        stage = s.strip()
        print(round(time.monotonic() - start, 2), stage, flush=True)


threading.Thread(target=reader, daemon=True).start()


def read(f):
    try:
        return int(pathlib.Path(f).read_text().strip())
    except:
        return None


with open(root / (name + ".jsonl"), "w") as f:
    tick = 0
    while p.poll() is None:
        processes = []
        for d in glob.glob("/sys/class/kfd/kfd/proc/[0-9]*"):
            queues = collections.Counter()
            for q in glob.glob(d + "/queues/[0-9]*"):
                key = (read(q + "/gpuid"), read(q + "/type"), read(q + "/size"))
                queues[key] += 1
            processes.append(
                {
                    "pid": int(d.rsplit("/", 1)[1]),
                    "queues": [
                        dict(gpuid=k[0], type=k[1], size=k[2], count=v)
                        for k, v in sorted(queues.items(), key=str)
                    ],
                }
            )
        g = []
        for d in sorted(glob.glob("/sys/class/drm/card[0-9]/device")):
            h = glob.glob(d + "/hwmon/hwmon*")[0]
            g.append(
                {
                    "card": d.split("/")[4],
                    "busy": read(d + "/gpu_busy_percent"),
                    "power_uw": read(h + "/power1_average"),
                }
            )
        row = {
            "t": round(time.monotonic() - start, 2),
            "stage": stage,
            "processes": processes,
            "gpus": g,
        }
        f.write(json.dumps(row) + "\n")
        f.flush()
        if tick % 10 == 0:
            print(json.dumps(row), flush=True)
        tick += 1
        time.sleep(0.5)
print("exit", p.returncode, flush=True)
