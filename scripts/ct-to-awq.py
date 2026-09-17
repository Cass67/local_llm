#!/usr/bin/env python3
"""Repack a compressed-tensors `pack-quantized` W4A16 checkpoint into AutoAWQ GEMM format.

Why: sglang's compressed-tensors wNa16 path is hard-wired to Marlin, which is
NVIDIA PTX and does not exist on ROCm. Its AWQ path, by contrast, dispatches to a
Triton dequantize kernel under `is_hip()`. The weights are the same int4 numbers
either way -- only the packing differs -- so a format transform is enough to make
a 4-bit checkpoint serve on gfx1100. No calibration, no requantization, no
additional quality loss.

This is the exact inverse of compressed_tensors' own AutoAWQConverter, and
`--validate` checks that by running that converter over the output and requiring
it to reproduce the input tensors bit-for-bit.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import torch
from compressed_tensors.compressors.pack_quantized.helpers import (
    pack_to_int32,
    unpack_from_int32,
)
from compressed_tensors.entrypoints.convert.converters.autoawq import AutoAWQConverter
from safetensors import safe_open
from safetensors.torch import save_file

BITS = 4
PACK = 32 // BITS  # 8 nibbles per int32
AWQ_REVERSE_ORDER = AutoAWQConverter.AWQ_REVERSE_ORDER  # [0, 4, 1, 5, 2, 6, 3, 7]


def _inverse_awq_order(n_cols: int, device: torch.device) -> torch.Tensor:
    """Column permutation that undoes AutoAWQConverter.reverse_awq_order.

    That converter *gathers* with AWQ_REVERSE_ORDER, so going the other way needs
    the inverse permutation, applied the same way.
    """
    order = torch.arange(n_cols, dtype=torch.long, device=device).view(-1, PACK)
    forward = order[:, AWQ_REVERSE_ORDER].reshape(-1)
    inverse = torch.empty_like(forward)
    inverse[forward] = torch.arange(n_cols, dtype=torch.long, device=device)
    return inverse


def _pack_awq(unsigned: torch.Tensor) -> torch.Tensor:
    """Pack [..., N] nibbles (0-15) into [..., N/8] int32, nibble j at bit 4*j."""
    rows, cols = unsigned.shape
    v = unsigned.to(torch.int32).view(rows, cols // PACK, PACK)
    shifts = (torch.arange(PACK, device=v.device, dtype=torch.int32) * BITS).view(1, 1, PACK)
    return (v << shifts).sum(dim=-1, dtype=torch.int32).contiguous()


def convert_module(
    weight_packed: torch.Tensor,
    weight_scale: torch.Tensor,
    weight_zero_point: torch.Tensor | None,
    weight_shape: torch.Tensor,
) -> dict[str, torch.Tensor]:
    """compressed-tensors module tensors -> AutoAWQ qweight / qzeros / scales.

    Shapes in: weight_packed [out, in/8], weight_scale [out, in/group],
    weight_zero_point [out/8, in/group] (packed along dim 0).
    Shapes out: qweight [in, out/8], scales [in/group, out], qzeros [in/group, out/8].
    """
    out_features, in_features = (int(x) for x in weight_shape.tolist())

    # int4 stored signed (-8..7); AWQ stores the unsigned 0..15 range.
    qweight = unpack_from_int32(weight_packed, BITS, torch.Size([out_features, in_features]))
    iweight = (qweight.to(torch.int32) + 2 ** (BITS - 1)).T.contiguous()  # [in, out]

    inv = _inverse_awq_order(iweight.shape[-1], iweight.device)
    out = {
        "qweight": _pack_awq(iweight[:, inv]),
        "scales": weight_scale.T.contiguous(),
    }

    if weight_zero_point is not None:
        n_groups = weight_scale.shape[1]
        izeros = unpack_from_int32(
            weight_zero_point, BITS, torch.Size([out_features, n_groups]), packed_dim=0
        )
        izeros = (izeros.to(torch.int32) + 2 ** (BITS - 1)).T.contiguous()  # [groups, out]
        out["qzeros"] = _pack_awq(izeros[:, _inverse_awq_order(izeros.shape[-1], izeros.device)])

    return out


def _module_names(keys: list[str]) -> list[str]:
    return sorted({k.removesuffix(".weight_packed") for k in keys if k.endswith(".weight_packed")})


def validate_module(src: dict[str, torch.Tensor], produced: dict[str, torch.Tensor]) -> None:
    """Round-trip through compressed_tensors' own converter and demand equality."""
    in_features = produced["qweight"].shape[0]
    conv = AutoAWQConverter(
        bits=BITS, group_size=in_features // src["weight_scale"].shape[1], ignore=()
    )
    tensors = {f"m.{k}": v for k, v in produced.items()}
    back = conv.process(dict(tensors))

    for name, want in (
        ("weight_packed", src["weight_packed"]),
        ("weight_scale", src["weight_scale"]),
        ("weight_zero_point", src.get("weight_zero_point")),
    ):
        if want is None:
            continue
        got = back[f"m.{name}"]
        if got.shape != want.shape or not torch.equal(got.cpu(), want.cpu()):
            raise SystemExit(
                f"round-trip mismatch on {name}: got {tuple(got.shape)} want {tuple(want.shape)}, "
                f"equal={torch.equal(got.cpu(), want.cpu()) if got.shape == want.shape else 'n/a'}"
            )


def convert_file(
    path: Path, out_path: Path, *, validate_n: int, device: str
) -> tuple[set[str], set[str]]:
    """Returns (quantized modules, modules left with a plain 2D .weight)."""
    plain_2d: set[str] = set()
    tensors: dict[str, torch.Tensor] = {}

    with safe_open(str(path), framework="pt", device=device) as f:
        keys = list(f.keys())
        metadata = f.metadata() or {}
        modules = set(_module_names(keys))
        quantized_suffixes = {
            "weight_packed",
            "weight_scale",
            "weight_zero_point",
            "weight_shape",
            "weight_g_idx",
        }

        for key in keys:
            module, _, suffix = key.rpartition(".")
            if module in modules and suffix in quantized_suffixes:
                continue
            tensor = f.get_tensor(key)
            if suffix == "weight" and tensor.ndim == 2:
                plain_2d.add(module)
            tensors[key] = tensor

        for i, module in enumerate(sorted(modules)):
            src = {
                s: f.get_tensor(f"{module}.{s}")
                for s in ("weight_packed", "weight_scale", "weight_zero_point", "weight_shape")
                if f"{module}.{s}" in keys
            }
            produced = convert_module(
                src["weight_packed"],
                src["weight_scale"],
                src.get("weight_zero_point"),
                src["weight_shape"],
            )
            if i < validate_n:
                validate_module(src, produced)
            for suffix, tensor in produced.items():
                tensors[f"{module}.{suffix}"] = tensor

    save_file(tensors, str(out_path), metadata={"format": "pt", **metadata})
    return modules, plain_2d


# Matched by substring against each layer's prefix (sglang: is_layer_skipped_awq).
# Every entry is checked against the real tensors by `verify_skip_list`, because a
# careless entry silently changes which layers get quantized: the source ignore
# list names the bare `linear_attn` module, yet its `in_proj_qkv` child IS
# quantized, so "linear_attn" as a substring would wrongly skip it.
SKIP_SUBSTRINGS = [
    "visual.",
    "lm_head",
    "mtp.",
    "embed_tokens",
    "in_proj_a",
    "in_proj_b",
    "linear_attn.norm",
]


def verify_skip_list(quantized: set[str], plain_2d: set[str], skips: list[str]) -> None:
    """Fail unless the substrings skip every plain module and no quantized one."""
    wrongly_skipped = sorted(m for m in quantized if any(s in m for s in skips))
    if wrongly_skipped:
        raise SystemExit(
            f"{len(wrongly_skipped)} quantized modules match the skip list, "
            f"e.g. {wrongly_skipped[:3]}"
        )
    unmatched = sorted(m for m in plain_2d if not any(s in m for s in skips))
    if unmatched:
        raise SystemExit(
            f"{len(unmatched)} unquantized modules are not covered by the skip list, "
            f"e.g. {unmatched[:5]}"
        )


def build_awq_config(src_config: dict, group_size: int) -> dict:
    """Swap the compressed-tensors block for an AutoAWQ one."""
    cfg = json.loads(json.dumps(src_config))
    cfg["quantization_config"] = {
        "quant_method": "awq",
        "bits": BITS,
        "group_size": group_size,
        "zero_point": True,
        "version": "gemm",
        "modules_to_not_convert": SKIP_SUBSTRINGS,
    }
    return cfg


def self_test(out_features: int = 64, in_features: int = 256, group_size: int = 128) -> None:
    """Round-trip synthetic int4 weights through the converter and back.

    Uses compressed_tensors' own AutoAWQConverter as the oracle: if this
    conversion is the true inverse, the oracle reproduces the input exactly.
    """
    g = torch.Generator().manual_seed(0)
    n_groups = in_features // group_size
    qweight = torch.randint(-8, 8, (out_features, in_features), generator=g, dtype=torch.int8)
    zeros = torch.randint(-8, 8, (out_features, n_groups), generator=g, dtype=torch.int8)
    src = {
        "weight_packed": pack_to_int32(qweight, BITS),
        "weight_scale": torch.rand(out_features, n_groups, generator=g).to(torch.bfloat16),
        "weight_zero_point": pack_to_int32(zeros, BITS, packed_dim=0).contiguous(),
        "weight_shape": torch.tensor([out_features, in_features]),
    }
    produced = convert_module(
        src["weight_packed"], src["weight_scale"], src["weight_zero_point"], src["weight_shape"]
    )
    shapes = {
        "qweight": (in_features, out_features // PACK),
        "scales": (n_groups, out_features),
        "qzeros": (n_groups, out_features // PACK),
    }
    for name, want_shape in shapes.items():
        if tuple(produced[name].shape) != want_shape:
            raise SystemExit(f"{name}: got {tuple(produced[name].shape)} want {want_shape}")

    validate_module(src, produced)

    # And the dequantized values themselves must match, independent of packing.
    want = (qweight.to(torch.float32) - zeros.repeat_interleave(group_size, dim=1)) * src[
        "weight_scale"
    ].to(torch.float32).repeat_interleave(group_size, dim=1)
    iw = unpack_from_int32(src["weight_packed"], BITS, torch.Size([out_features, in_features]))
    if not torch.equal(iw, qweight):
        raise SystemExit("source unpack disagrees with what we packed")
    print(f"self-test ok (max |dequant| {want.abs().max():.3f})")


def write_index(dst: Path) -> None:
    weight_map: dict[str, str] = {}
    total = 0
    for shard in sorted(dst.glob("*.safetensors")):
        with safe_open(str(shard), framework="pt", device="cpu") as f:
            for key in f.keys():  # noqa: SIM118 - safe_open has no __iter__
                weight_map[key] = shard.name
                t = f.get_slice(key)
                total += _numel(t.get_shape()) * _dtype_size(t.get_dtype())
    (dst / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {"total_size": total}, "weight_map": weight_map}, indent=2) + "\n"
    )


def _numel(shape: list[int]) -> int:
    n = 1
    for d in shape:
        n *= d
    return n


def _dtype_size(dtype: str) -> int:
    return {"BOOL": 1, "U8": 1, "I8": 1, "I16": 2, "U16": 2, "F16": 2, "BF16": 2}.get(dtype, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--src", type=Path)
    ap.add_argument("--dst", type=Path)
    ap.add_argument("--validate-n", type=int, default=2, help="modules per file to round-trip")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.src or not args.dst:
        raise SystemExit("--src and --dst are required")

    args.dst.mkdir(parents=True, exist_ok=True)
    shards = sorted(args.src.glob("*.safetensors"))
    if not shards:
        raise SystemExit(f"no safetensors under {args.src}")

    src_config = json.loads((args.src / "config.json").read_text())
    qcfg = src_config.get("quantization_config") or {}
    group_size = qcfg["config_groups"]["group_0"]["weights"]["group_size"]

    quantized: set[str] = set()
    plain_2d: set[str] = set()
    for shard in shards:
        q, p = convert_file(
            shard, args.dst / shard.name, validate_n=args.validate_n, device=args.device
        )
        quantized |= q
        plain_2d |= p
        print(f"{shard.name}: {len(q)} modules", flush=True)

    verify_skip_list(quantized, plain_2d, SKIP_SUBSTRINGS)
    total = len(quantized)

    (args.dst / "config.json").write_text(
        json.dumps(build_awq_config(src_config, group_size), indent=2) + "\n"
    )
    for extra in args.src.iterdir():
        if (
            extra.suffix in {".json", ".jinja", ".txt"}
            and extra.name != "config.json"
            and not extra.name.endswith(".index.json")
        ):
            shutil.copy2(extra, args.dst / extra.name)

    # The source index maps the old weight_packed names; rebuild it from what we
    # actually wrote or the loader looks for tensors that no longer exist.
    write_index(args.dst)

    print(f"converted {total} modules -> {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
