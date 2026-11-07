#!/bin/bash
# att.sh OUTDIR FLAGS... : trace 2 s of a story decode with the given rocprofv3 flags, copy CSVs to OUTDIR
R=local-llm-runner-cluster-7900s-maya-0663b08f
out=$1
shift
(cd ~/scratch/ds4-ab && python3 -c "import pair; pair.req(pair.PROMPTS[\"story\"])" &)
sleep 10
docker exec $R rm -rf /tmp/rp
docker exec --privileged $R /opt/rocm/bin/rocprofv3 --attach 8 --attach-duration-msec 2000 "$@" --output-format csv -d /tmp/rp -o t 2>&1 | grep -E "Error|error|success" | head -3
for _ in $(seq 40); do
  docker exec $R sh -c "ls /tmp/rp/*kernel_trace.csv" >/dev/null 2>&1 && break
  sleep 3
done
sleep 5
rm -rf "$out"
docker cp "$R:/tmp/rp" "$out" >/dev/null
ls "$out"
sleep 25
