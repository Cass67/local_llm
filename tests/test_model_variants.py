import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))

from backend.model_variants import (  # noqa: E402
    _BACKEND_SUFFIXES,
    backend_variant_id,
    base_variant_id,
)


def test_longest_suffix_wins():
    """Order matters: "-rocmunsloth" must strip before "-rocm", or a variant keeps a stub."""
    assert base_variant_id("qwopus-rocmunsloth") == "qwopus"
    assert base_variant_id("qwopus-rocmunslothsrc") == "qwopus"
    assert base_variant_id("qwopus-rocmfp4") == "qwopus"
    assert base_variant_id("qwopus-rocm") == "qwopus"
    assert base_variant_id("qwopus") == "qwopus"


def test_copying_between_backends_does_not_accumulate_suffixes():
    """The bug the derived suffix list fixes: foo-rocmunsloth -> foo-rocmunsloth-rocm."""
    assert backend_variant_id("qwopus-rocmunsloth", "rocm") == "qwopus-rocm"
    assert backend_variant_id("qwopus-rocm", "rocmunsloth") == "qwopus-rocmunsloth"
    assert backend_variant_id("qwopus", "rocmunsloth") == "qwopus-rocmunsloth"


def test_every_backend_round_trips():
    for suffix in _BACKEND_SUFFIXES:
        backend = suffix.lstrip("-")
        assert base_variant_id(backend_variant_id("qwopus", backend)) == "qwopus"
