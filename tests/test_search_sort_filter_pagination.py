from __future__ import annotations

import pytest
from scripts.model_manager.tui_helpers import (
    filter_candidates,
    paginate_candidates,
    sort_candidates,
)


@pytest.fixture
def candidates():
    return [
        {"repo": "alpha", "score": 80, "best_quant": "Q4_K_M"},
        {"repo": "beta", "score": 95, "best_quant": "Q6_K"},
        {"repo": "gamma", "score": 70, "best_quant": "Q8_0"},
        {"repo": "delta", "score": 85, "best_quant": "Q4_K_M"},
    ]


class TestSortCandidates:
    def test_sort_by_score_desc(self, candidates):
        result = sort_candidates(candidates, "score")
        repos = [c["repo"] for c in result]
        assert repos == ["beta", "delta", "alpha", "gamma"]

    def test_sort_by_repo_asc(self, candidates):
        result = sort_candidates(candidates, "repo")
        repos = [c["repo"] for c in result]
        assert repos == ["alpha", "beta", "delta", "gamma"]

    def test_sort_by_quant_asc(self, candidates):
        result = sort_candidates(candidates, "quant")
        quants = [c["best_quant"] for c in result]
        assert quants == ["Q4_K_M", "Q4_K_M", "Q6_K", "Q8_0"]

    def test_unknown_mode_returns_original_order(self, candidates):
        result = sort_candidates(candidates, "unknown")
        assert result is candidates


class TestFilterCandidates:
    def test_filter_by_repo_substring(self, candidates):
        result = filter_candidates(candidates, "beta")
        assert len(result) == 1
        assert result[0]["repo"] == "beta"

    def test_filter_by_quant_substring(self, candidates):
        result = filter_candidates(candidates, "Q4_K_M")
        assert len(result) == 2
        repos = [c["repo"] for c in result]
        assert set(repos) == {"alpha", "delta"}

    def test_filter_no_match(self, candidates):
        result = filter_candidates(candidates, "zzzz")
        assert len(result) == 0

    def test_filter_empty_text_returns_all(self, candidates):
        result = filter_candidates(candidates, "")
        assert result is candidates


class TestPaginateCandidates:
    def test_first_page(self, candidates):
        page, per_page = 1, 2
        _, _, items = paginate_candidates(candidates, page, per_page)
        repos = [c["repo"] for c in items]
        assert repos == ["alpha", "beta"]

    def test_second_page(self, candidates):
        page, per_page = 2, 2
        _, _, items = paginate_candidates(candidates, page, per_page)
        repos = [c["repo"] for c in items]
        assert repos == ["gamma", "delta"]

    def test_out_of_range_returns_last_page_not_empty(self, candidates):
        _, total_pages, items = paginate_candidates(candidates, 5, 2)
        assert total_pages == 2
        assert items == candidates[-2:]  # clamped to last page

    def test_negative_page_clamped_to_1(self, candidates):
        _, _, items = paginate_candidates(candidates, -1, 2)
        repos = [c["repo"] for c in items]
        assert repos == ["alpha", "beta"]
