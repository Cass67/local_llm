"""Golden-prompt checks — degenerate output must fail, good output must pass."""

import pytest
from backend import measure, quality, sweep


def _case(**kw):
    return {"id": "t", "prompt": "p", **kw}


def test_good_response_passes():
    result = quality.check_response(
        _case(min_words=3, must_match=[r"def\s+foo"]), "def foo(): pass"
    )
    assert result["passed"]
    assert result["failures"] == []


def test_short_output_fails():
    result = quality.check_response(_case(min_words=150), "too short")
    assert not result["passed"]
    assert "expected at least 150" in result["failures"][0]


def test_missing_pattern_fails():
    result = quality.check_response(_case(must_match=[r"ZEPHYR-4417"]), "I don't recall the token.")
    assert not result["passed"]
    assert "missing expected pattern" in result["failures"][0]


def test_forbidden_pattern_fails():
    result = quality.check_response(_case(must_not_match=[r"as an AI"]), "As an AI, I cannot.")
    assert not result["passed"]


def test_repetition_loop_is_caught():
    text = "\n".join(["The answer is definitely this one."] * 20)
    result = quality.check_response(_case(min_words=1), text)
    assert not result["passed"]
    assert "degenerate repetition" in result["failures"][0]


def test_varied_output_is_not_flagged_as_repetitive():
    text = "\n".join(f"Line number {i} says something different entirely." for i in range(20))
    assert quality.repetition_ratio(text) < quality.MAX_REPETITION_RATIO
    assert quality.check_response(_case(min_words=1), text)["passed"]


def test_short_output_never_counts_as_repetitive():
    assert quality.repetition_ratio("one line only, quite long though") == 0.0


def test_default_cases_are_wellformed():
    for case in quality.DEFAULT_CASES:
        assert case["id"] and case["prompt"]
        assert isinstance(case.get("min_words", 0), int)


@pytest.fixture
def stub_chat(monkeypatch):
    replies: dict[str, str] = {}

    def fake(_port, _model, prompt, _system, _max_tokens, _timeout):
        return {"text": replies.get(prompt, ""), "decode_tps": 10.0}

    monkeypatch.setattr(measure, "chat_once", fake)
    return replies


def test_run_quality_reports_pass_rate(stub_chat):
    cases = [
        _case(id="a", prompt="a?", min_words=1, must_match=["yes"]),
        _case(id="b", prompt="b?", min_words=1, must_match=["no"]),
    ]
    stub_chat["a?"] = "yes indeed"
    stub_chat["b?"] = "maybe"
    report = quality.run_quality(8081, "m", cases=cases)
    assert report["passed"] == 1
    assert report["total"] == 2
    assert report["pass_rate"] == 0.5


def test_request_failure_counts_as_a_failed_case(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(measure, "chat_once", boom)
    report = quality.run_quality(8081, "m", cases=[_case(min_words=1)])
    assert report["pass_rate"] == 0.0
    assert "connection refused" in report["cases"][0]["failures"][0]


def test_judge_score_parsed_and_averaged(stub_chat, monkeypatch):
    monkeypatch.setattr(quality, "judge_response", lambda *_a, **_k: 4)
    stub_chat["a?"] = "an answer"
    report = quality.run_quality(
        8081, "m", cases=[_case(prompt="a?", min_words=1)], judge_url="http://j/v1", judge_model="j"
    )
    assert report["judge_mean"] == 4.0


def test_unreachable_judge_does_not_fail_the_run(stub_chat, monkeypatch):
    monkeypatch.setattr(quality, "judge_response", lambda *_a, **_k: None)
    stub_chat["a?"] = "an answer"
    report = quality.run_quality(
        8081, "m", cases=[_case(prompt="a?", min_words=1)], judge_url="http://j/v1", judge_model="j"
    )
    assert report["judge_mean"] is None
    assert report["pass_rate"] == 1.0


# --- sweep integration: the gate must actually block a winner ---


def test_quality_gate_excludes_fast_but_broken_config(tmp_path, monkeypatch):
    import json

    from backend.clusters import ClusterDef

    monkeypatch.setattr(sweep.config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(sweep.config, "ACCEPTED_DIR", tmp_path / "runs" / "accepted")
    monkeypatch.setattr(sweep.config, "PROFILES_CONFIG", tmp_path / "profiles.json")
    sweep.config.ACCEPTED_DIR.mkdir(parents=True)
    (sweep.config.ACCEPTED_DIR / "fam.json").write_text(
        json.dumps({"family": "fam", "alias": "fam-model", "model_path": "/m.gguf"})
    )
    sweep.config.PROFILES_CONFIG.write_text(
        json.dumps(
            {
                "families": {
                    "fam": {
                        "default": "balanced",
                        # spec_type must be on, or the linter correctly skips every
                        # mtp_draft_p_min combo as dead config.
                        "profiles": {"balanced": {"ngl": 999, "spec_type": "draft-mtp"}},
                    }
                }
            }
        )
    )
    # Golden set narrowed to the one thing this sweep can break: prose length.
    monkeypatch.setattr(quality.config, "STATE_DIR", tmp_path)
    (tmp_path / "quality_set.json").write_text(
        json.dumps({"cases": [{"id": "prose", "prompt": "explain", "min_words": 150}]})
    )
    cluster = ClusterDef(
        id="c1",
        name="c1",
        gpu_pci_ids=["0000:01:00.0"],
        backend="rocm",
        port=8081,
        container_name="c",
    )
    monkeypatch.setattr(sweep, "get_cluster", lambda _cid: cluster)
    monkeypatch.setattr(sweep.active_runners, "start", lambda _c, _meta: None)

    # p_min 0.9 is much faster but produces half-length prose.
    def fake_chat(_port, _model, _prompt, _system, _max_tokens, _timeout):
        cfg = sweep.base_profile_config("fam", "balanced-sweep") or {}
        fast = cfg.get("mtp_draft_p_min") == 0.9
        return {
            "decode_tps": 90.0 if fast else 30.0,
            "prompt_tps": 900.0,
            "completion_tokens": 100,
            "wall_s": 1.0,
            "text": "short." if fast else " ".join(["word"] * 400),
        }

    monkeypatch.setattr(measure, "chat_once", fake_chat)

    job = sweep.SweepJob(
        family="fam",
        cluster_id="c1",
        base_profile="balanced",
        grid={"mtp_draft_p_min": [0.4, 0.9]},
        prompt_text="hi",
        repeats=1,
        warmup=0,
        quality_gate=True,
    )
    job.start()
    job._thread.join(10)

    by_pmin = {r["combo"]["mtp_draft_p_min"]: r for r in job.results}
    assert by_pmin[0.9]["decode_tps"] == 90.0  # measured, and reported
    assert by_pmin[0.9]["quality_gate"] == "failed"  # but not eligible
    assert job.best()["combo"] == {"mtp_draft_p_min": 0.4}
