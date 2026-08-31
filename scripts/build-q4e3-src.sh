#!/usr/bin/env bash
# Rebuild the pre-merged llama.cpp tree for runner/rocmqwen4exp3.
#
# master + PR #27836 (NextN/MTP draft head) + PR #27879 (qwen4exp correctness).
# Both PRs are still open upstream and both rewrite src/models/qwen4exp.cpp, so they
# conflict exactly once, in the is_ple() tensor block. The resolution below keeps
# #27879's corrected dims (ple_dim) and #27836's `flags` argument.
#
# usage: scripts/build-q4e3-src.sh <dest-dir>
set -euo pipefail
DEST=${1:?usage: build-q4e3-src.sh <dest-dir>}

rm -rf "$DEST"; mkdir -p "$DEST"; cd "$DEST"
git init -q .
git remote add up https://github.com/ggml-org/llama.cpp.git
git fetch -q --depth 200 up master
git fetch -q --depth 200 up pull/27836/head:pr27836
git fetch -q --depth 200 up pull/27879/head:pr27879
git checkout -q -b work up/master

git merge --no-edit pr27836                 # merges clean
git merge --no-edit pr27879 || true         # conflicts in qwen4exp.cpp

python3 - <<'PY'
p = "src/models/qwen4exp.cpp"
s = open(p).read()
start = s.index("<<<<<<< HEAD")
end   = s.index(">>>>>>> pr27879")
resolved = """            const int64_t ple_dim = (int64_t) hparams.ple_head_dim * hparams.ple_n_heads;
            layer.ple_key        = create_tensor(tn(LLM_TENSOR_PLE_KEY,        "weight", il), { ple_dim, hc_dim }, flags);
            layer.ple_value      = create_tensor(tn(LLM_TENSOR_PLE_VALUE,      "weight", il), { ple_dim, n_embd }, flags);
            layer.ple_norm_key   = create_tensor(tn(LLM_TENSOR_PLE_NORM_KEY,   "weight", il), { hc_dim }, flags);
            layer.ple_norm_query = create_tensor(tn(LLM_TENSOR_PLE_NORM_QUERY, "weight", il), { hc_dim }, flags);
            layer.ple_norm_conv  = create_tensor(tn(LLM_TENSOR_PLE_NORM_CONV,  "weight", il), { hc_dim }, flags);
            layer.ple_conv1d     = create_tensor(tn(LLM_TENSOR_PLE_CONV1D,     "weight", il), { hparams.ple_conv_kernel, hc_dim }, flags);
"""
s = s[:start] + resolved + s[end + len(">>>>>>> pr27879") + 1:]
open(p, "w").write(s)
assert "<<<<<<<" not in s
PY

git add src/models/qwen4exp.cpp
git commit -q -m "merge PR 27836 (MTP) + PR 27879 (qwen4exp correctness) onto master"

# Port the fork's sidecar MTP loader (Nathanw1014 35439081). PR #27836 only supports MTP
# weights baked into the main GGUF; our drafter is a standalone 34-tensor sidecar, which
# upstream rejects with "tensor 'blk.0.hc_attn_norm.weight' not found" because the trunk
# tensors stay required. Make the trunk optional when the file is MTP-only.
python3 - <<'PY'
p = "src/models/qwen4exp.cpp"
s = open(p).read()
anchor = "    const int mtp_flags = !ml.load_mtp ? TENSOR_SKIP : 0;\n"
assert anchor in s
s = s.replace(anchor, anchor + '''
    // A sidecar drafter GGUF carries ONLY the trailing MTP block (e.g. blk.48 of a 49-block
    // model) plus token_embd/output. Upstream #27836 assumes the MTP weights are baked into the
    // main file, so the trunk tensors below stay required and a sidecar fails to load with
    // "tensor 'blk.0.hc_attn_norm.weight' not found". Detect that and make the trunk optional.
    // Ported from Nathanw1014/llama.cpp 35439081, which PR #27836 does not carry.
    const bool mtp_only = hparams.n_layer_nextn > 0 &&
                          ml.get_weight("blk.0.hc_attn_norm.weight") == nullptr;
    const int trunk_flags = mtp_only ? TENSOR_NOT_REQUIRED : 0;
''', 1)
old = "        const int flags = il < n_layer ? 0 : mtp_flags;"
assert old in s
s = s.replace(old, "        const int flags = il < n_layer ? trunk_flags : mtp_flags;", 1)
open(p, "w").write(s)
PY
git add src/models/qwen4exp.cpp
git commit -q -m "qwen4exp: allow a sidecar-only MTP GGUF (port of fork 35439081)"
echo "merged tree at $DEST ($(git rev-parse --short HEAD))"
