"""Minimal GGUF header reader — enough metadata to predict VRAM use.

Only the key-value header is parsed; tensor data is never read, so this is a few
KB of IO regardless of model size.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_MAGIC = b"GGUF"

# GGUF metadata value type enum
_UINT8, _INT8, _UINT16, _INT16, _UINT32, _INT32, _FLOAT32 = range(7)
_BOOL, _STRING, _ARRAY, _UINT64, _INT64, _FLOAT64 = range(7, 13)

_FIXED = {
    _UINT8: ("<B", 1),
    _INT8: ("<b", 1),
    _UINT16: ("<H", 2),
    _INT16: ("<h", 2),
    _UINT32: ("<I", 4),
    _INT32: ("<i", 4),
    _FLOAT32: ("<f", 4),
    _BOOL: ("<?", 1),
    _UINT64: ("<Q", 8),
    _INT64: ("<q", 8),
    _FLOAT64: ("<d", 8),
}


@dataclass
class GgufMeta:
    arch: str
    n_layers: int
    n_head_kv: int
    key_length: int
    value_length: int
    file_bytes: int


class _Reader:
    def __init__(self, fh):
        self.fh = fh

    def raw(self, n: int) -> bytes:
        data = self.fh.read(n)
        if len(data) != n:
            raise ValueError("truncated GGUF header")
        return data

    def fixed(self, vtype: int):
        fmt, size = _FIXED[vtype]
        return struct.unpack(fmt, self.raw(size))[0]

    def string(self) -> str:
        length = struct.unpack("<Q", self.raw(8))[0]
        return self.raw(length).decode("utf-8", errors="replace")

    def value(self, vtype: int):
        if vtype in _FIXED:
            return self.fixed(vtype)
        if vtype == _STRING:
            return self.string()
        if vtype == _ARRAY:
            elem_type = struct.unpack("<I", self.raw(4))[0]
            count = struct.unpack("<Q", self.raw(8))[0]
            # Arrays are only tokenizer vocabs here — skip the contents rather than
            # materialising a 150k-entry list we will never look at.
            if elem_type in _FIXED:
                self.raw(_FIXED[elem_type][1] * count)
            elif elem_type == _STRING:
                for _ in range(count):
                    self.string()
            else:
                raise ValueError(f"unsupported GGUF array element type {elem_type}")
            return None
        raise ValueError(f"unsupported GGUF value type {vtype}")


def read_gguf_meta(path: str | Path) -> GgufMeta | None:
    """Parse a GGUF header. Returns None if the file is missing or not GGUF."""
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if fh.read(4) != _MAGIC:
                return None
            struct.unpack("<I", fh.read(4))[0]  # version
            r = _Reader(fh)
            struct.unpack("<Q", r.raw(8))[0]  # tensor count
            kv_count = struct.unpack("<Q", r.raw(8))[0]
            kv: dict[str, object] = {}
            for _ in range(kv_count):
                key = r.string()
                vtype = struct.unpack("<I", r.raw(4))[0]
                kv[key] = r.value(vtype)
    except (OSError, ValueError, struct.error):
        return None

    arch = str(kv.get("general.architecture") or "")

    def num(suffix: str, default: int = 0) -> int:
        value = kv.get(f"{arch}.{suffix}")
        return int(value) if isinstance(value, (int, float)) else default

    n_layers = num("block_count")
    n_head_kv = num("attention.head_count_kv") or num("attention.head_count")
    n_embd = num("embedding_length")
    n_head = num("attention.head_count")
    head_dim = (n_embd // n_head) if n_head else 0
    key_length = num("attention.key_length") or head_dim
    value_length = num("attention.value_length") or head_dim

    if not (n_layers and n_head_kv and key_length):
        return None
    return GgufMeta(
        arch=arch,
        n_layers=n_layers,
        n_head_kv=n_head_kv,
        key_length=key_length,
        value_length=value_length,
        file_bytes=size,
    )


# KV cache element size in bytes per type name accepted by --cache-type-k/-v
_KV_BYTES = {
    "f32": 4.0,
    "f16": 2.0,
    "bf16": 2.0,
    "q8_0": 1.0625,
    "q5_1": 0.75,
    "q5_0": 0.6875,
    "q4_1": 0.625,
    "q4_0": 0.5625,
    "iq4_nl": 0.5625,
}


def kv_cache_mb(meta: GgufMeta, ctx: int, cache_type_k: str, cache_type_v: str) -> float:
    k_bytes = _KV_BYTES.get(cache_type_k.lower(), 2.0)
    v_bytes = _KV_BYTES.get(cache_type_v.lower(), 2.0)
    per_token = meta.n_head_kv * (meta.key_length * k_bytes + meta.value_length * v_bytes)
    return meta.n_layers * ctx * per_token / (1024 * 1024)
