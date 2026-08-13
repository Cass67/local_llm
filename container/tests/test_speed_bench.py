"""SPEED-Bench: placeholder rows are dropped, acceptance is pooled over tokens."""

import pytest
from backend import speed_bench


def _row(category, qid, turns, multiturn=False):
    return {"category": category, "question_id": qid, "turns": turns, "multiturn": multiturn}


def test_placeholders_are_dropped_and_counted(monkeypatch):
    rows = [
        _row("code", "a", ["write a parser"]),
        _row("code", "b", [speed_bench.PLACEHOLDER]),
        _row("prose", "c", ["turn one", speed_bench.PLACEHOLDER]),  # any turn poisons the row
        _row("prose", "d", ["describe a storm"]),
    ]
    monkeypatch.setattr(speed_bench, "_fetch_rows", lambda: rows)

    keep, dropped = speed_bench.load_prompts()
    assert [r["question_id"] for r in keep] == ["a", "d"]
    assert dropped == {"code": 1, "prose": 1}

    listing = speed_bench.categories()
    assert listing["usable_total"] == 2
    assert listing["placeholder_total"] == 2
    assert listing["categories"][0] == {"name": "code", "usable": 1, "placeholders": 1}


def test_acceptance_is_pooled_over_tokens_not_averaged_over_rows():
    # A row that drafted 100 tokens must outweigh one that drafted 2.
    rows = [
        {
            "category": "code",
            "draft_n": 100,
            "draft_accepted": 20,
            "cover_pct": 50.0,
            "tg_tok_s": 40.0,
        },
        {
            "category": "code",
            "draft_n": 2,
            "draft_accepted": 2,
            "cover_pct": 10.0,
            "tg_tok_s": 30.0,
        },
    ]
    summary = speed_bench.summarise(rows)
    code = summary["per_category"][0]
    assert code["accept_pct"] == pytest.approx(21.6)  # 22/102, not (20% + 100%)/2
    assert code["n"] == 2
    assert summary["overall"]["accept_pct"] == pytest.approx(21.6)


def test_select_rows_caps_per_category_and_filters():
    prompts = [_row("code", f"c{i}", ["x"]) for i in range(5)]
    prompts += [_row("math", f"m{i}", ["x"]) for i in range(5)]
    prompts += [_row("prose", "p0", ["x"])]

    selected = speed_bench.select_rows(prompts, ["code", "math"], 2)
    assert [r["question_id"] for r in selected] == ["c0", "c1", "m0", "m1"]
    # No filter means every domain.
    assert len(speed_bench.select_rows(prompts, [], 1)) == 3


def test_run_row_sums_turns_and_derives_rates(monkeypatch):
    payloads = [
        {
            "choices": [{"message": {"content": "one"}}],
            "timings": {
                "prompt_n": 10,
                "predicted_n": 100,
                "draft_n": 80,
                "draft_n_accepted": 40,
                "predicted_per_second": 50.0,
            },
        },
        {
            "choices": [{"message": {"reasoning_content": "two"}}],  # empty content is legal
            "timings": {
                "prompt_n": 5,
                "predicted_n": 100,
                "draft_n": 20,
                "draft_n_accepted": 20,
                "predicted_per_second": 30.0,
            },
        },
    ]
    monkeypatch.setattr(speed_bench, "_chat", lambda *a, **k: payloads.pop(0))

    result = speed_bench.run_row(8080, "m", _row("code", "a", ["t1", "t2"]), 256, 60.0)
    assert result["draft_n"] == 100
    assert result["draft_accepted"] == 60
    assert result["accept_pct"] == 60.0
    assert result["cover_pct"] == 50.0  # 100 drafted of 200 predicted
    assert result["tg_tok_s"] == 40.0  # mean of the two turns
