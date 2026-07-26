"""Images must route to a model whose running profile loaded an mmproj."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import model_router as mr  # noqa: E402

IMAGE_MSG = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "fix this bug in the code"},  # would match a code rule
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }
]


def _setup(vision: set[str]) -> None:
    mr._healthy_aliases = {"blind-model", "seeing-model"}
    mr._cluster_to_model = {"P40": "blind-model", "7900sv": "seeing-model"}
    mr._vision_aliases = vision
    mr.RULES = [{"name": "code", "keywords": ["bug"], "model": "blind-model"}]
    mr.DEFAULT_MODEL = "blind-model"


def test_image_overrides_keyword_rule():
    _setup({"seeing-model"})
    detail = mr._route_detail(IMAGE_MSG)
    assert detail == {"model": "seeing-model", "reason": "vision"}, detail


def test_text_only_still_uses_rules():
    _setup({"seeing-model"})
    detail = mr._route_detail([{"role": "user", "content": "fix this bug"}])
    assert detail["model"] == "blind-model", detail


def test_no_vision_model_falls_back_to_rules():
    _setup(set())
    assert mr._route_detail(IMAGE_MSG)["model"] == "blind-model"


if __name__ == "__main__":
    test_image_overrides_keyword_rule()
    test_text_only_still_uses_rules()
    test_no_vision_model_falls_back_to_rules()
    print("ok")
