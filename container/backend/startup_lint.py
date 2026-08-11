"""Scan llama-server boot output for knobs it silently declined to honour.

llama.cpp disables features at load time (cache reuse, RCCL, speculative decoding)
and only says so once, in the startup log, at a level nobody reads. Each hit here
is a knob the profile sets that is not actually in effect.
"""

from __future__ import annotations

import re

# (compiled pattern, short id, message shown in the UI)
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"cache_reuse.*will be disabled", re.I),
        "cache_reuse_disabled",
        "--cache-reuse was disabled by llama-server (an mmproj is loaded, or this model "
        "cannot KV-shift). The cache_reuse profile field has no effect on this run.",
    ),
    (
        re.compile(r"context shift.*(disabled|not supported)", re.I),
        "context_shift_disabled",
        "Context shifting is unavailable for this model; long sessions will hit the ctx "
        "wall instead of sliding.",
    ),
    (
        re.compile(r"failed to (init|initialize).*(rccl|nccl)", re.I),
        "rccl_unavailable",
        "RCCL failed to initialise — tensor split falls back to the slow butterfly "
        "all-reduce. Check the runner image was built with RCCL and that ShmSize is large "
        "enough.",
    ),
    (
        re.compile(r"the draft model.*(vocab|incompatible)", re.I),
        "draft_vocab_mismatch",
        "The draft model's vocabulary does not match the target model; speculative "
        "decoding is off.",
    ),
    (
        re.compile(r"spec.*(boundary|mismatch).*fallback", re.I),
        "spec_boundary_fallback",
        "Speculative decoding is hitting spec-boundary mismatches and falling back to cold "
        "prompt processing — set cache_reuse to recover the cache hits.",
    ),
    (
        re.compile(r"flash.?attn.*(not supported|disabled|unavailable)", re.I),
        "flash_attention_unavailable",
        "Flash attention is not available for this model/backend combination; the "
        "flash_attention profile field is not in effect.",
    ),
    (
        re.compile(r"(unknown|unrecognized) argument", re.I),
        "unknown_argument",
        "llama-server reported an unknown argument — check the raw 'flags' field against "
        "the binary in this runner image.",
    ),
    (
        re.compile(r"failed to allocate|out of memory|ggml_backend_alloc", re.I),
        "vram_pressure",
        "An allocation failed during load — reduce context, ubatch, or quantize the KV cache.",
    ),
    (
        re.compile(r"using CPU backend|no usable GPU|no GPU (found|detected)", re.I),
        "running_on_cpu",
        "No usable GPU was found — this runner is on the CPU backend and will be unusably slow.",
    ),
    (
        re.compile(r"n_ctx_per_seq.*less than.*n_ctx_train", re.I),
        "ctx_below_trained",
        "Context is set below what the model was trained for; you are leaving usable "
        "context on the table.",
    ),
]


def scan_startup_log(lines: list[str]) -> list[dict[str, str]]:
    """Return one finding per distinct issue seen in the boot log."""
    seen: dict[str, dict[str, str]] = {}
    for line in lines:
        for pattern, key, message in _PATTERNS:
            if key not in seen and pattern.search(line):
                seen[key] = {"id": key, "message": message, "line": line.strip()[:300]}
    return list(seen.values())
