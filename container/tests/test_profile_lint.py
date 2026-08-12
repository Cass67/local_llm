"""Profile linter — dead knobs must be reported, valid profiles must stay silent."""

import re
import struct
from pathlib import Path

from backend.gguf_meta import kv_cache_mb, read_gguf_meta
from backend.profile_lint import KNOWN_FIELDS, estimate_vram_mb, lint_profile

RUNTIME_SRC = Path(__file__).resolve().parents[1] / "backend" / "runtime.py"


def _levels(findings, field):
    return [f["level"] for f in findings if f["field"] == field]


def test_known_fields_covers_every_key_runtime_reads():
    """Guard against drift: a new cfg.get() in runtime.py must be added to KNOWN_FIELDS."""
    src = RUNTIME_SRC.read_text()
    read_keys = set(re.findall(r'cfg\.get\(\s*"([a-z0-9_]+)"', src))
    missing = read_keys - KNOWN_FIELDS
    assert not missing, f"runtime.py reads keys the linter would call unknown: {sorted(missing)}"


def test_clean_profile_has_no_findings():
    profile = {
        "ngl": 999,
        "batch": 4096,
        "ubatch": 512,
        "context": 65536,
        "flash_attention": True,
        "cache_type_k": "q8_0",
        "parallel": 1,
    }
    assert lint_profile(profile) == []


def test_nested_mtp_block_flagged():
    findings = lint_profile({"mtp": {"enabled": True, "draft_n_max": 2}})
    assert _levels(findings, "mtp") == ["error"]


def test_raw_flag_key_flagged():
    findings = lint_profile({"spec-draft-n-max": 2})
    assert _levels(findings, "spec-draft-n-max") == ["error"]


def test_typo_gets_suggestion():
    findings = lint_profile({"mtpenabled": True})
    assert "mtp_enabled" in findings[0]["message"]


def test_spec_fields_without_spec_type_flagged():
    findings = lint_profile({"mtp_draft_n_max": 2, "ngram_mod_n_match": 24})
    assert _levels(findings, "spec_type") == ["error"]


def test_dflash_without_draft_gguf_flagged():
    findings = lint_profile({"spec_type": "draft-dflash"})
    assert _levels(findings, "mtp_draft_model") == ["error"]
    assert lint_profile({"spec_type": "draft-dflash", "mtp_draft_model": "/m/d.gguf"}) == []


def test_ngram_mod_n_min_unset_flagged():
    findings = lint_profile({"spec_type": "ngram-mod", "ngram_mod_n_match": 24})
    assert _levels(findings, "ngram_mod_n_min") == ["warn"]


def test_tensor_split_rejects_quantized_kv_and_needs_fa():
    findings = lint_profile(
        {"split_mode": "tensor", "cache_type_k": "q8_0", "cache_type_v": "q8_0"}
    )
    assert _levels(findings, "cache_type_k") == ["error"]
    assert _levels(findings, "flash_attention") == ["error"]
    assert (
        lint_profile({"split_mode": "tensor", "cache_type_k": "f16", "flash_attention": True}) == []
    )


def test_tensor_split_width_must_match_visible_devices():
    findings = lint_profile({"tensor_split": "1,1,1", "visible_devices": "0,1"})
    assert _levels(findings, "tensor_split") == ["error"]


def test_tensor_split_zero_weight_flagged():
    assert _levels(lint_profile({"tensor_split": "0,1"}), "tensor_split") == ["error"]
    assert _levels(lint_profile({"tensor_split": "1,1"}), "tensor_split") == []


def test_ubatch_larger_than_batch_flagged():
    findings = lint_profile({"batch": 512, "ubatch": 4096})
    assert _levels(findings, "ubatch") == ["error"]


def test_mmproj_disables_cache_reuse():
    findings = lint_profile({"mmproj": "/m/mmproj.gguf", "cache_reuse": 256})
    assert _levels(findings, "cache_reuse") == ["warn"]


def test_promoted_flag_in_raw_flags_flagged():
    findings = lint_profile({"flags": "--parallel 4"})
    assert _levels(findings, "flags") == ["warn"]


# --- GGUF header + VRAM estimate ---


def _write_gguf(path: Path, *, layers=48, head_kv=8, head_count=40, embd=5120, pad=4096):
    """Write a minimal but structurally real GGUF header."""

    def kv_str(key, value):
        return (
            struct.pack("<Q", len(key))
            + key.encode()
            + struct.pack("<I", 8)
            + struct.pack("<Q", len(value))
            + value.encode()
        )

    def kv_u32(key, value):
        return (
            struct.pack("<Q", len(key))
            + key.encode()
            + struct.pack("<I", 4)
            + struct.pack("<I", value)
        )

    entries = [
        kv_str("general.architecture", "llama"),
        kv_u32("llama.block_count", layers),
        kv_u32("llama.attention.head_count_kv", head_kv),
        kv_u32("llama.attention.head_count", head_count),
        kv_u32("llama.embedding_length", embd),
    ]
    body = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(entries))
    body += b"".join(entries)
    path.write_bytes(body + b"\0" * pad)


def test_gguf_header_parses(tmp_path):
    p = tmp_path / "m.gguf"
    _write_gguf(p)
    meta = read_gguf_meta(p)
    assert meta is not None
    assert (meta.n_layers, meta.n_head_kv, meta.key_length) == (48, 8, 128)


def test_non_gguf_file_returns_none(tmp_path):
    p = tmp_path / "not.gguf"
    p.write_bytes(b"not a gguf at all")
    assert read_gguf_meta(p) is None


def test_kv_cache_scales_with_quantization(tmp_path):
    p = tmp_path / "m.gguf"
    _write_gguf(p)
    meta = read_gguf_meta(p)
    f16 = kv_cache_mb(meta, 65536, "f16", "f16")
    q8 = kv_cache_mb(meta, 65536, "q8_0", "q8_0")
    # 48 layers * 65536 ctx * 8 kv heads * 128 dim * 2 (K+V) * 2 bytes
    assert round(f16) == 12288
    assert q8 < f16


def test_vram_overflow_is_an_error(tmp_path):
    p = tmp_path / "m.gguf"
    _write_gguf(p, pad=20 * 1024 * 1024)
    profile = {"context": 131072, "cache_type_k": "f16", "cache_type_v": "f16"}
    est = estimate_vram_mb(profile, p)
    assert est["kv_mb"] > 20000
    findings = lint_profile(profile, model_path=p, vram_mb=20480)
    assert _levels(findings, "context") == ["error"]
    assert "OOM" in findings[0]["message"]


def test_vram_within_budget_is_silent(tmp_path):
    p = tmp_path / "m.gguf"
    _write_gguf(p, pad=8 * 1024 * 1024)
    profile = {"context": 8192, "cache_type_k": "q8_0", "cache_type_v": "q8_0"}
    assert lint_profile(profile, model_path=p, vram_mb=20480) == []
