# Model Discovery Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank live Hugging Face GGUF candidates for the RX 7900 XT so target-size models appear before tiny or huge models.

**Architecture:** Keep ranking inside the existing Python block in `scripts/model-discovery.sh`. Expand the fixture and shell tests to prove target, unknown, small, and huge buckets render in the desired order.

**Tech Stack:** Bash, Python stdlib `json`/`re`, existing `test_oc_local.sh`, `shellcheck`.

---

## File Structure

- Modify `testdata/huggingface-model-search.json`: add target, small, huge, and unknown candidates with download counts that would sort poorly without local ranking.
- Modify `test_oc_local.sh`: assert ranking order and new `class=` labels.
- Modify `scripts/model-discovery.sh`: classify sizes, rank locally, and render `class=` plus better fit notes.
- Modify `README.md`: briefly document target-size ranking and tiny demotion.

## Task 1: Add Ranking Regression Test

**Files:**
- Modify: `testdata/huggingface-model-search.json`
- Modify: `test_oc_local.sh`

- [ ] **Step 1: Expand fixture**

Replace `testdata/huggingface-model-search.json` with:

```json
[
  {
    "id": "TinyOrg/Tiny-1B-GGUF",
    "downloads": 9999999,
    "likes": 100,
    "tags": ["gguf", "text-generation"]
  },
  {
    "id": "HugeOrg/Huge-70B-GGUF",
    "downloads": 8888888,
    "likes": 100,
    "tags": ["gguf", "reasoning"]
  },
  {
    "id": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
    "downloads": 1200,
    "likes": 45,
    "tags": ["gguf", "llama.cpp", "text-generation", "code"]
  },
  {
    "id": "unsloth/gpt-oss-20b-GGUF",
    "downloads": 900,
    "likes": 40,
    "tags": ["gguf", "llama.cpp", "reasoning"]
  },
  {
    "id": "OddOrg/Odd-E4B-GGUF",
    "downloads": 2000,
    "likes": 20,
    "tags": ["gguf", "text-generation"]
  },
  {
    "id": "example/not-a-gguf-model",
    "downloads": 5000,
    "likes": 100,
    "tags": ["safetensors"]
  }
]
```

- [ ] **Step 2: Add order assertions**

In `test_oc_local.sh`, after existing fixture assertions for `model_discovery_output`, add:

```bash
assert_contains "$model_discovery_output" "class=target"
assert_contains "$model_discovery_output" "class=small"
assert_contains "$model_discovery_output" "class=huge"
assert_contains "$model_discovery_output" "class=unknown"

target_line="$(printf '%s\n' "$model_discovery_output" | grep -n 'unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF' | cut -d: -f1)"
small_line="$(printf '%s\n' "$model_discovery_output" | grep -n 'TinyOrg/Tiny-1B-GGUF' | cut -d: -f1)"
huge_line="$(printf '%s\n' "$model_discovery_output" | grep -n 'HugeOrg/Huge-70B-GGUF' | cut -d: -f1)"
if (( target_line >= small_line || small_line >= huge_line )); then
  printf 'expected target before small before huge in model discovery output\n%s\n' "$model_discovery_output" >&2
  exit 1
fi
```

- [ ] **Step 3: Run failing test**

Run: `./test_oc_local.sh`

Expected: FAIL because current output does not include `class=` labels or ranking buckets.

## Task 2: Implement Bucketed Ranking

**Files:**
- Modify: `scripts/model-discovery.sh`

- [ ] **Step 1: Replace Python candidate loop**

In `render_hf_candidates()`, replace the Python logic after JSON parsing with code that builds a candidate list, ranks it, and prints up to the requested limit. Use this logic:

```python
def size_class(sizes):
    if any(size >= 70 for size in sizes):
        return (3, "huge", "unlikely", "too large for this tuned fleet without major tradeoffs")
    if any(14 <= size <= 40 for size in sizes):
        size = max(size for size in sizes if 14 <= size <= 40)
        return (0, "target", "maybe", f"{size}B target-size candidate for RX 7900 XT tuning")
    if any(1 <= size <= 9 for size in sizes):
        size = max(size for size in sizes if 1 <= size <= 9)
        return (2, "small", "small/test", f"{size}B tiny model, demoted for this hardware")
    return (1, "unknown", "unknown", "inspect quant and context before pulling")

def relevance_score(haystack):
    score = 0
    for token in ("code", "coder", "reasoning", "r1", "qwen", "gemma", "gpt-oss"):
        if token in haystack:
            score += 1
    return score
```

Sort candidates by:

```python
candidate.sort_key = (bucket_rank, -relevance, -downloads, repo.lower())
```

Print:

```python
print(f"- {repo} | purpose={purpose} | class={bucket_name} | fit={fit} | {note}")
```

- [ ] **Step 2: Pass limit into renderer**

Change `render_hf_candidates()` so the Python block receives `limit` as an argument:

```bash
render_hf_candidates() {
  python3 - "$limit" <<'PY'
...
limit = int(sys.argv[1])
...
PY
}
```

Keep stdin JSON parsing intact.

- [ ] **Step 3: Run tests**

Run: `./test_oc_local.sh`

Expected: PASS.

Run: `bash -n scripts/model-discovery.sh test_oc_local.sh && shellcheck scripts/model-discovery.sh test_oc_local.sh`

Expected: no output, exit 0.

## Task 3: Update Docs And Install

**Files:**
- Modify: `README.md`
- Installed output: `/Users/cass/.local/bin/model-discovery`

- [ ] **Step 1: Update README**

Add this sentence to the Model Discovery section:

```markdown
Default results are ranked for the RX 7900 XT: 14B-40B candidates first, unusual sizes next, tiny 1B-9B models demoted as small/test, and 70B+ models demoted as unlikely.
```

- [ ] **Step 2: Install updated script**

Run:

```bash
install -m 0755 scripts/model-discovery.sh /Users/cass/.local/bin/model-discovery
```

Expected: no output, exit 0.

- [ ] **Step 3: Verify live output**

Run: `model-discovery --limit 8`

Expected: output includes `class=target`, and any 1B/70B results appear after target-size candidates.

## Self-Review

- Spec coverage: target ranking, tiny demotion, huge demotion, unknown retention, relevance boost, and download tiebreak are covered.
- Placeholder scan: no placeholder steps remain.
- Type consistency: `class=target|unknown|small|huge` appears in tests, docs, and renderer.
