# Qwen Vision And Quant Benchmark Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable vision by default for existing Qwen 35B launchers and benchmark stronger Qwen 35B quant/KV profiles on `ubt26`.

**Architecture:** Keep the existing shortcut families and dynamic user systemd selector. Change launcher flags and metadata first, then run a controlled remote benchmark matrix before promoting quant/KV/MMQ defaults.

**Tech Stack:** Bash, llama.cpp `llama-server`, Hugging Face GGUF repos, user systemd on `ubt26`, shell tests.

---

### Task 1: Add Failing Tests For Qwen Vision Defaults

**Files:**
- Modify: `test_oc_local.sh`

**Step 1: Write failing tests**

Add assertions near the existing `start3.sh` and `start11.sh` checks:

```bash
start3_contents="$(<"$repo_root/scripts/start3.sh")"
assert_contains "$start3_contents" "--mmproj-auto"
assert_not_contains "$start3_contents" "--no-mmproj"

start11_contents="$(<"$repo_root/scripts/start11.sh")"
assert_contains "$start11_contents" "--mmproj-auto"
assert_not_contains "$start11_contents" "--no-mmproj"
```

Add assertions to the existing `run_info qwen ...` and `run_info qwen-hauhau ...` blocks:

```bash
assert_contains "$fastlong_output" "mmproj=enabled"
assert_contains "$qwen_hauhau_info" "mmproj=enabled"
```

**Step 2: Verify failure**

Run: `bash test_oc_local.sh`

Expected: FAIL because `start3.sh`, `start11.sh`, and metadata still disable or omit mmproj.

### Task 2: Enable Qwen 35B Vision In Launchers And Metadata

**Files:**
- Modify: `scripts/start3.sh`
- Modify: `scripts/start11.sh`
- Modify: `scripts/oc-local`

**Step 1: Update launchers**

In `scripts/start3.sh`, replace:

```bash
--no-mmproj \
```

with:

```bash
--mmproj-auto \
```

In `scripts/start11.sh`, make the same replacement.

**Step 2: Update metadata**

In `scripts/oc-local`, change the `qwen` and `qwen-hauhau` family cases from:

```bash
mmproj_mode=none
```

to:

```bash
mmproj_mode=enabled
```

**Step 3: Verify tests pass for this change**

Run: `bash -n scripts/oc-local scripts/start3.sh scripts/start11.sh test_oc_local.sh`

Expected: exit code 0.

Run: `shellcheck scripts/oc-local scripts/start3.sh scripts/start11.sh test_oc_local.sh`

Expected: exit code 0.

Run: `bash test_oc_local.sh`

Expected: Qwen vision assertions pass. If the known `model-discovery.sh` fixture failure remains, record it as unrelated.

### Task 3: Install And Copy Vision-Enabled Launchers

**Files:**
- Local installed: `~/.local/bin/oc-local`
- Remote: `/home/cass/llama.cpp/start3.sh`
- Remote: `/home/cass/llama.cpp/start11.sh`

**Step 1: Reinstall local wrapper**

Run: `./installer.sh`

Expected: exit code 0.

**Step 2: Copy launchers to remote**

Run:

```bash
scp scripts/start3.sh scripts/start11.sh ubt26:/home/cass/llama.cpp/
ssh ubt26 'chmod +x /home/cass/llama.cpp/start3.sh /home/cass/llama.cpp/start11.sh && bash -n /home/cass/llama.cpp/start3.sh /home/cass/llama.cpp/start11.sh'
```

Expected: exit code 0.

### Task 4: Smoke Test Vision-Enabled Qwen Startup

**Files:**
- Remote service state: `/home/cass/llama.cpp/current-model.env`
- Remote logs: `/home/cass/llama.cpp/llama-*.log` or `journalctl --user -u llama-server.service`

**Step 1: Start Qwen Hauhau reliable via user service**

Run:

```bash
ssh ubt26 'cd /home/cass/llama.cpp && cat > current-model.env <<"EOF"
REMOTE_SCRIPT=./start11.sh
REMOTE_PROFILE=reliable
EOF
systemctl --user restart llama-server.service'
```

Expected: service restarts.

**Step 2: Wait for API**

Run:

```bash
ssh ubt26 'for i in $(seq 1 180); do curl -fsS --max-time 2 http://127.0.0.1:8080/v1/models && exit 0; sleep 2; done; exit 1'
```

Expected: JSON model response for `qwen3.6-35b-a3b-hauhau`.

**Step 3: Verify projector load status**

Run:

```bash
ssh ubt26 'journalctl --user -u llama-server.service -n 160 --no-pager | grep -Ei "mmproj|projector|clip|vision|multimodal" || true'
```

Expected: logs show mmproj/projector loaded, or clearly show no projector available. Record exact outcome.

### Task 5: Benchmark Quant/KV/MMQ Matrix

**Files:**
- Create: `docs/benchmarks/2026-05-22-qwen-vision-quant.md`

**Step 1: Identify available Qwen 35B files**

Run:

```bash
ssh ubt26 'python3 - <<"PY"
from huggingface_hub import list_repo_files
for repo in ["unsloth/Qwen3.6-35B-A3B-MTP-GGUF", "HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive"]:
    print(repo)
    for name in list_repo_files(repo):
        if name.endswith(".gguf") or "mmproj" in name.lower():
            print("  ", name)
PY'
```

Expected: list of candidate `Q4_K_M`, `Q5_K_M`, `Q6_K`, `IQ4_XS`, and projector files if present.

**Step 2: Run controlled startup/completion probes**

For each selected candidate, run a temporary llama-server command with:

```bash
--mmproj-auto --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on
```

Test context `32768` first, then `65536` for candidates that fit. Repeat best candidates with:

```bash
GGML_HIP_FORCE_MMQ=1
```

Record load success, prompt eval tok/s, decode tok/s, and VRAM/oom notes.

**Step 3: Write benchmark report**

Create `docs/benchmarks/2026-05-22-qwen-vision-quant.md` with a table:

```markdown
| Family | Repo | GGUF | Context | KV | MMQ | mmproj | Status | Prompt tok/s | Decode tok/s | Notes |
| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | --- |
```

### Task 6: Promote Winning Defaults

**Files:**
- Modify: `scripts/start3.sh`
- Modify: `scripts/start11.sh`
- Modify: `scripts/oc-local`
- Modify: `README.md`
- Modify: `test_oc_local.sh`

**Step 1: Update default profile values only if benchmark supports it**

Apply the smallest change needed for the selected winner: GGUF file, batch/ubatch/context, KV flags, and optional `GGML_HIP_FORCE_MMQ=1` if it clearly wins.

**Step 2: Update tests**

Adjust expected `quant=`, command, context, batch, and mmproj lines for the promoted defaults.

**Step 3: Update README**

Document that Qwen 35B defaults are vision-enabled and list the chosen recommended Qwen command.

**Step 4: Verify**

Run:

```bash
bash -n scripts/oc-local installer.sh scripts/start3.sh scripts/start11.sh test_oc_local.sh
shellcheck scripts/oc-local installer.sh scripts/start3.sh scripts/start11.sh test_oc_local.sh
bash test_oc_local.sh
```

Expected: syntax and shellcheck pass. Full test may still hit the unrelated `model-discovery.sh` fixture failure; record exact status.

### Task 7: Final Remote Verification

**Files:**
- Remote: `/home/cass/llama.cpp/start3.sh`
- Remote: `/home/cass/llama.cpp/start11.sh`
- Remote: `/home/cass/llama.cpp/current-model.env`

**Step 1: Copy final launchers**

Run:

```bash
scp scripts/start3.sh scripts/start11.sh ubt26:/home/cass/llama.cpp/
```

**Step 2: Start promoted default**

Run either `oc-qwen-hauhau --lean --info` locally for inspection, then start it normally, or update `current-model.env` and restart the user service directly.

**Step 3: Probe API**

Run:

```bash
ssh ubt26 'curl -fsS http://127.0.0.1:8080/v1/models && curl -fsS http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" --data "{\"model\":\"qwen3.6-35b-a3b-hauhau\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: ok\"}],\"max_tokens\":8,\"temperature\":0}"'
```

Expected: model list returns the selected Qwen model and chat probe returns sane text.
