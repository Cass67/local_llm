"""Occupancy-aware routing: a busy primary yields to an idle same-tier fallback."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import model_router as mr  # noqa: E402

CODE_MSG = [{"role": "user", "content": "implement a retry decorator for the http client"}]


@pytest.fixture(autouse=True)
def clean_router():
    mr._healthy_aliases = {"hard-model", "hard-model-2", "easy-model"}
    mr._cluster_to_model = {
        "7900sv": "hard-model",
        "7900sr": "hard-model-2",
        "P40": "easy-model",
    }
    mr._vision_aliases = set()
    mr.CLUSTER_REMAP = {}
    mr._inflight = {}
    mr._cluster_occupancy = {}
    mr._decision_log = []
    mr.RULES = [
        {
            "name": "code",
            "keywords": ["implement"],
            "cluster": "7900sv",
            "fallback": ["7900sr", "P40"],
        }
    ]
    mr.DEFAULT_MODEL = None
    mr.DEFAULT_CLUSTER = "7900sv"
    mr.PREFER_IDLE = False
    mr.SHADOW = False
    yield
    mr._inflight = {}


def test_idle_primary_is_used_normally():
    mr.PREFER_IDLE = True
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "hard-model"
    assert detail["reason"] == "rule"


def test_busy_primary_yields_to_idle_fallback():
    mr.PREFER_IDLE = True
    mr._inflight = {"hard-model": 1}
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "hard-model-2"
    assert detail["reason"] == "idle-fallback"
    assert detail["busy_primary"] == "hard-model"


def test_prefer_idle_off_keeps_the_busy_primary():
    mr.PREFER_IDLE = False
    mr._inflight = {"hard-model": 3}
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "hard-model"
    assert detail["reason"] == "rule"


def test_all_busy_falls_back_to_the_least_loaded():
    mr.PREFER_IDLE = True
    mr._inflight = {"hard-model": 3, "hard-model-2": 1, "easy-model": 2}
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "hard-model-2"


def test_gpu_occupancy_breaks_ties_between_idle_clusters():
    mr.PREFER_IDLE = True
    # No in-flight requests, but fdinfo says the primary is still finishing work.
    mr._cluster_occupancy = {"7900sv": 0.9, "7900sr": 0.0}
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "hard-model-2"
    assert detail["reason"] == "idle-fallback"


def test_unhealthy_fallback_is_never_chosen():
    mr.PREFER_IDLE = True
    mr._healthy_aliases = {"hard-model"}
    mr._inflight = {"hard-model": 5}
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "hard-model"


def test_inflight_tracking_increments_and_releases():
    release = mr._acquire_inflight("hard-model")
    assert mr._inflight["hard-model"] == 1
    second = mr._acquire_inflight("hard-model")
    assert mr._inflight["hard-model"] == 2
    release()
    assert mr._inflight["hard-model"] == 1
    second()
    assert "hard-model" not in mr._inflight


def test_release_is_idempotent():
    release = mr._acquire_inflight("hard-model")
    release()
    release()
    assert "hard-model" not in mr._inflight


def test_empty_alias_is_not_tracked():
    mr._acquire_inflight("")()
    assert mr._inflight == {}


def test_decision_log_is_bounded():
    for i in range(mr._DECISION_LOG_MAX + 50):
        mr._log_decision({"prompt": str(i)})
    assert len(mr._decision_log) == mr._DECISION_LOG_MAX
    assert mr._decision_log[-1]["prompt"] == str(mr._DECISION_LOG_MAX + 49)


def test_busy_score_prefers_inflight_over_occupancy():
    # One in-flight request outranks any amount of sampled occupancy.
    mr._inflight = {"hard-model": 1}
    mr._cluster_occupancy = {"7900sr": 1.99}
    assert mr._busy_score("hard-model") > mr._busy_score("hard-model-2")
