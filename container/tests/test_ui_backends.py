import re
from pathlib import Path

from backend.clusters import _VALID_BACKENDS

TYPES_TS = Path(__file__).resolve().parents[2] / "ui/src/lib/types.ts"


def test_ui_backend_list_matches_backend():
    src = TYPES_TS.read_text()
    backends = re.search(r"export const BACKENDS = \[(.*?)\] as const", src, re.S).group(1)
    labels = re.search(r"BACKEND_LABELS: Record<Backend, string> = \{(.*?)\};", src, re.S).group(1)
    assert set(re.findall(r'"(\w+)"', backends)) == _VALID_BACKENDS
    assert set(re.findall(r"^\s*(\w+):", labels, re.M)) == _VALID_BACKENDS
