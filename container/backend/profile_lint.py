"""Profile validation — catch fields and combinations that silently do nothing.

Nothing here rejects a profile. llama.cpp ignores unknown keys and quietly disables
knobs it cannot honour, so the whole point is to say so out loud at save time
instead of leaving the user to infer it from a benchmark that didn't move.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .gguf_meta import kv_cache_mb, read_gguf_meta

# Every key runtime.py actually reads. tests/test_profile_lint.py cross-checks this
# against the cfg.get() calls in runtime.py so the two cannot drift apart.
KNOWN_FIELDS: set[str] = {
    # placement / container wiring
    "backend",
    "visible_devices",
    "mixed_vulkan",
    "nvidia_vulkan",
    "split_mode",
    "tensor_split",
    "main_gpu",
    "ngl",
    # context and batching
    "ctx",
    "context",
    "batch",
    "ubatch",
    "context_shift",
    "cache_prompt",
    "cache_ram",
    "cache_reuse",
    "ctx_checkpoints",
    "checkpoint_min_step",
    "cache_type_k",
    "cache_type_v",
    "no_kv_offload",
    "kv_unified",
    # sampling
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "repetition_penalty",
    "presence_penalty",
    "frequency_penalty",
    "penalty_last_n",
    "dry_multiplier",
    "dry_base",
    "dry_allowed_length",
    "dry_penalty_last_n",
    # reasoning
    "reasoning",
    "reasoning_budget",
    "reasoning_budget_message",
    # speculative decoding
    "spec_type",
    "mtp_enabled",
    "mtp_draft_model",
    "mtp_draft_hf_repo",
    "mtp_draft_hf_file",
    "mtp_draft_n_max",
    "mtp_draft_n_min",
    "mtp_draft_p_min",
    "mtp_draft_ngl",
    "ngram_mod_n_match",
    "ngram_mod_n_min",
    "ngram_mod_n_max",
    # serving
    "timeout",
    "threads",
    "threads_batch",
    "threads_http",
    "parallel",
    "no_cont_batching",
    "prio",
    "no_warmup",
    "backend_sampling",
    "load_timeout_s",
    # misc
    "flash_attention",
    "jinja",
    "mmproj",
    "no_mmap",
    "mlock",
    "numa",
    "flags",
    "quant",
}

_SPEC_NEEDS_DRAFT_GGUF = {"draft-dflash", "draft-simple", "draft-eagle3"}
_SPEC_FIELDS = {
    "mtp_draft_model",
    "mtp_draft_hf_repo",
    "mtp_draft_hf_file",
    "mtp_draft_n_max",
    "mtp_draft_n_min",
    "mtp_draft_p_min",
    "mtp_draft_ngl",
    "ngram_mod_n_match",
    "ngram_mod_n_min",
    "ngram_mod_n_max",
}
_UNQUANTIZED_KV = {"f16", "bf16", "f32"}


def _finding(level: str, field: str, message: str) -> dict[str, str]:
    return {"level": level, "field": field, "message": message}


def _lint_unknown(profile: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for key, value in profile.items():
        if key in KNOWN_FIELDS:
            continue
        if key == "mtp" and isinstance(value, dict):
            out.append(
                _finding(
                    "error",
                    "mtp",
                    "nested 'mtp' object is not read — use the flat mtp_enabled / "
                    "mtp_draft_n_max keys. This profile has no working speculative decoding.",
                )
            )
        elif "-" in key:
            out.append(
                _finding(
                    "error",
                    key,
                    f"'{key}' looks like a raw CLI flag; profile keys use underscores. "
                    "Put unrecognised flags in the 'flags' string instead.",
                )
            )
        else:
            close = [k for k in KNOWN_FIELDS if k.replace("_", "") == key.replace("_", "")]
            hint = f" Did you mean '{close[0]}'?" if close else ""
            out.append(_finding("error", key, f"unknown field '{key}' — silently ignored.{hint}"))
    return out


def _lint_spec(profile: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    spec_type = str(profile.get("spec_type") or "").strip()
    kinds = {t.strip() for t in spec_type.split(",") if t.strip()}
    if profile.get("mtp_enabled") and not spec_type:
        kinds = {"draft-mtp"}

    if not kinds:
        stale = sorted(_SPEC_FIELDS & set(profile))
        if stale:
            out.append(
                _finding(
                    "error",
                    "spec_type",
                    f"{', '.join(stale)} set but neither spec_type nor mtp_enabled is — "
                    "speculative decoding is off and these fields do nothing.",
                )
            )
        return out

    if kinds & _SPEC_NEEDS_DRAFT_GGUF and not (
        profile.get("mtp_draft_model")
        or (profile.get("mtp_draft_hf_repo") and profile.get("mtp_draft_hf_file"))
    ):
        out.append(
            _finding(
                "error",
                "mtp_draft_model",
                f"{','.join(sorted(kinds & _SPEC_NEEDS_DRAFT_GGUF))} needs a separate draft GGUF — "
                "set mtp_draft_model or mtp_draft_hf_repo + mtp_draft_hf_file.",
            )
        )

    if "ngram-mod" in kinds:
        n_match = profile.get("ngram_mod_n_match")
        if n_match is not None and int(n_match) < 24:
            out.append(
                _finding(
                    "warn",
                    "ngram_mod_n_match",
                    f"n_match={n_match} is below 24; llama.cpp warns about draft quality here.",
                )
            )
        if not profile.get("ngram_mod_n_min"):
            out.append(
                _finding(
                    "warn",
                    "ngram_mod_n_min",
                    "ngram_mod_n_min unset/0 while ngram-mod is on — costs roughly 20% of the "
                    "speedup. Track it with ngram_mod_n_match.",
                )
            )

    if "draft-mtp" in kinds and profile.get("mtp_draft_p_min") is not None:
        out.append(
            _finding(
                "warn",
                "mtp_draft_p_min",
                "grafted MTP heads have uncalibrated confidence; gating on p_min usually loses "
                "more than it saves. Leave it unset unless measured.",
            )
        )
    # Scoped to draft-mtp on purpose. A DFlash2 sidecar is trained to emit a whole
    # block at once and measures fastest at its block_size (7 after llama.cpp's
    # clamp, ~2.24x vs 1.98x at 3 on Qwen3.8-27B) -- warning there is backwards.
    if "draft-mtp" in kinds and (profile.get("mtp_draft_n_max") or 0) > 3:
        out.append(
            _finding(
                "warn",
                "mtp_draft_n_max",
                "draft depth above 3 degrades on grafted MTP heads.",
            )
        )
    return out


def _lint_split_mode(profile: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    split_mode = str(profile.get("split_mode") or "")
    kv_k = str(profile.get("cache_type_k") or "f16").lower()
    kv_v = str(profile.get("cache_type_v") or "f16").lower()

    if split_mode == "tensor":
        bad_kv = [
            n
            for n, t in (("cache_type_k", kv_k), ("cache_type_v", kv_v))
            if t not in _UNQUANTIZED_KV
        ]
        if bad_kv:
            out.append(
                _finding(
                    "error",
                    bad_kv[0],
                    "split_mode 'tensor' requires f16/bf16 KV; quantized KV makes the runner fail "
                    "or fall back. Do not copy q8_0 KV over from a layer-split profile.",
                )
            )
        if not profile.get("flash_attention"):
            out.append(
                _finding(
                    "error",
                    "flash_attention",
                    "split_mode 'tensor' requires flash attention.",
                )
            )
    if split_mode == "row":
        out.append(
            _finding(
                "warn", "split_mode", "'row' is deprecated and removed upstream; use 'tensor'."
            )
        )
    return out


def _lint_shapes(profile: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    tensor_split = str(profile.get("tensor_split") or "")
    visible = str(profile.get("visible_devices") or "")
    if tensor_split and visible:
        n_split = len([p for p in tensor_split.split(",") if p.strip()])
        n_visible = len([p for p in visible.split(",") if p.strip()])
        if n_split != n_visible:
            out.append(
                _finding(
                    "error",
                    "tensor_split",
                    f"tensor_split has {n_split} weights but visible_devices lists {n_visible} "
                    "GPUs.",
                )
            )

    # A zero weight excludes that GPU entirely, so the whole model lands on the
    # others. "0,1" reads like a device list but means "nothing on card 0" —
    # the runner then OOMs on the last card and blames the model size.
    weights = [w.strip() for w in tensor_split.split(",") if w.strip()]
    if len(weights) > 1 and any(w in ("0", "0.0") for w in weights):
        out.append(
            _finding(
                "error",
                "tensor_split",
                f"tensor_split '{tensor_split}' gives a GPU zero weight, loading the whole "
                "model onto the rest. These are proportions, not device indices — use '1,1'.",
            )
        )

    # -c is the total KV budget shared by the slots, not a per-request size. With a
    # non-unified cache llama_n_ctx_seq() hands each slot ctx/parallel, so a big ctx
    # here does not mean a big context per request.
    parallel = int(profile.get("parallel") or 1)
    ctx = profile.get("ctx") or profile.get("context")
    if parallel > 1 and not profile.get("kv_unified") and ctx:
        out.append(
            _finding(
                "warn",
                "parallel",
                f"parallel {parallel} without kv_unified splits ctx {int(ctx)} across the slots — "
                f"each request gets {int(ctx) // parallel}. Set kv_unified or raise ctx.",
            )
        )

    # The penalty samplers score only the last --repeat-last-n tokens (llama.cpp
    # default 64). A repeated sentence fills that window within a few repeats and
    # presence penalty, which is flat per-token and does not escalate with count,
    # stops pushing away from the loop.
    penalising = (
        any(float(profile.get(k) or 0) > 0 for k in ("presence_penalty", "frequency_penalty"))
        or float(profile.get("repetition_penalty") or profile.get("repeat_penalty") or 1) > 1
    )
    if penalising and profile.get("penalty_last_n") is None:
        out.append(
            _finding(
                "warn",
                "penalty_last_n",
                "penalties are set but penalty_last_n is not — llama.cpp scores only the "
                "last 64 tokens, which a looping sentence fills in a few repeats. "
                "Set penalty_last_n (~1024), and dry_multiplier for sequence-level loops.",
            )
        )

    batch = profile.get("batch")
    ubatch = profile.get("ubatch")
    if batch is not None and ubatch is not None and int(ubatch) > int(batch):
        out.append(_finding("error", "ubatch", f"ubatch ({ubatch}) exceeds batch ({batch})."))

    if profile.get("ctx") is not None and profile.get("context") is not None:
        if int(profile["ctx"]) != int(profile["context"]):
            out.append(
                _finding(
                    "warn",
                    "ctx",
                    f"ctx ({profile['ctx']}) and context ({profile['context']}) disagree; "
                    "ctx wins.",
                )
            )

    if profile.get("mmproj") and profile.get("cache_reuse"):
        out.append(
            _finding(
                "warn",
                "cache_reuse",
                "a loaded mmproj silently disables --cache-reuse; check the startup log for "
                "'cache_reuse ... will be disabled'.",
            )
        )
    return out


def _lint_flags(profile: dict[str, Any]) -> list[dict[str, str]]:
    from .runtime import build_llama_server_args

    raw = str(profile.get("flags") or "").split()
    if not raw:
        return []
    emitted = set(
        build_llama_server_args(
            {"model_path": "/dev/null", "config": {"flags": profile.get("flags")}}, port=0
        )
    )
    dropped = [tok for tok in raw if tok.startswith("-") and tok not in emitted]
    if dropped:
        return [
            _finding(
                "warn",
                "flags",
                f"{' '.join(dropped)} is already covered by a structured field and is stripped "
                "from flags — set the field instead.",
            )
        ]
    return []


def estimate_vram_mb(profile: dict[str, Any], model_path: str | Path) -> dict[str, Any] | None:
    """Predict VRAM for this profile. None when the GGUF can't be read."""
    meta = read_gguf_meta(model_path)
    if meta is None:
        return None
    ctx = int(profile.get("ctx") or profile.get("context") or 0)
    if ctx <= 0:
        return None
    weights_mb = meta.file_bytes / (1024 * 1024)
    kv_mb = kv_cache_mb(
        meta,
        ctx,
        str(profile.get("cache_type_k") or "f16"),
        str(profile.get("cache_type_v") or "f16"),
    )
    # Compute buffers scale with the physical micro-batch, not the logical one.
    ubatch = int(profile.get("ubatch") or 512)
    compute_mb = 0.5 * ubatch + 512
    return {
        "weights_mb": round(weights_mb),
        "kv_mb": round(kv_mb),
        "compute_mb": round(compute_mb),
        "total_mb": round(weights_mb + kv_mb + compute_mb),
        "n_layers": meta.n_layers,
        "ctx": ctx,
    }


def _lint_vram(
    profile: dict[str, Any], model_path: str | Path | None, vram_mb: int | None
) -> list[dict[str, str]]:
    if not model_path or not vram_mb:
        return []
    est = estimate_vram_mb(profile, model_path)
    if est is None:
        return []
    total = est["total_mb"]
    if total > vram_mb:
        over = total - vram_mb
        return [
            _finding(
                "error",
                "context",
                f"estimated {total} MB (weights {est['weights_mb']} + KV {est['kv_mb']} @ "
                f"{est['ctx']} ctx) exceeds {vram_mb} MB of VRAM by {over} MB — this will OOM.",
            )
        ]
    if total > vram_mb * 0.95:
        return [
            _finding(
                "warn",
                "context",
                f"estimated {total} MB of {vram_mb} MB VRAM — under 5% headroom.",
            )
        ]
    return []


def lint_profile(
    profile: dict[str, Any],
    *,
    model_path: str | Path | None = None,
    vram_mb: int | None = None,
) -> list[dict[str, str]]:
    """Return findings for a profile. level is 'error' (does nothing / will fail) or 'warn'."""
    if not isinstance(profile, dict):
        return [_finding("error", "", "profile must be a JSON object")]
    findings = [
        *_lint_unknown(profile),
        *_lint_spec(profile),
        *_lint_split_mode(profile),
        *_lint_shapes(profile),
        *_lint_flags(profile),
        *_lint_vram(profile, model_path, vram_mb),
    ]
    return findings
