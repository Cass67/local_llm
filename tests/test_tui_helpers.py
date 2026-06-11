from scripts.model_manager.tui_helpers import (
    filter_candidates,
    paginate_candidates,
    sort_candidates,
)


def test_filter_candidates_matches_repo_quant_and_file():
    candidates = [
        {"repo": "google/gemma", "best_quant": "Q4_K_M", "best_file": "gemma-q4.gguf"},
        {"repo": "Qwen/Qwen3", "best_quant": "Q8_0", "best_file": "qwen-q8.gguf"},
        {"repo": "meta/llama", "best_quant": "Q4_K_M", "best_file": "llama-q4.gguf"},
    ]

    assert [c["repo"] for c in filter_candidates(candidates, "qwen")] == ["Qwen/Qwen3"]
    assert [c["repo"] for c in filter_candidates(candidates, "q4")]
    assert filter_candidates(candidates, "") == candidates


def test_sort_candidates_by_score_quant_or_repo():
    candidates = [
        {"repo": "b/model", "score": 2, "best_quant": "Q4_K_M"},
        {"repo": "a/model", "score": 9, "best_quant": "Q8_0"},
        {"repo": "c/model", "score": "bad", "best_quant": "Q2_K"},
    ]

    assert [c["repo"] for c in sort_candidates(candidates, "score")] == [
        "a/model",
        "b/model",
        "c/model",
    ]
    assert [c["repo"] for c in sort_candidates(candidates, "repo")] == [
        "a/model",
        "b/model",
        "c/model",
    ]
    assert [c["repo"] for c in sort_candidates(candidates, "quant")] == [
        "c/model",
        "b/model",
        "a/model",
    ]


def test_paginate_candidates_clamps_pages():
    candidates = [{"repo": f"m{i}"} for i in range(25)]

    page, total_pages, page_items = paginate_candidates(candidates, page=2, per_page=10)
    assert page == 2
    assert total_pages == 3
    assert [c["repo"] for c in page_items] == [f"m{i}" for i in range(10, 20)]

    page, total_pages, page_items = paginate_candidates(candidates, page=99, per_page=10)
    assert page == 3
    assert total_pages == 3
    assert [c["repo"] for c in page_items] == [f"m{i}" for i in range(20, 25)]

    page, total_pages, page_items = paginate_candidates([], page=1, per_page=10)
    assert page == 1
    assert total_pages == 1
    assert page_items == []
