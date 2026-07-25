"""Profile names must not fork on case — see _resolve_name in routes.profiles."""

from backend.routes.profiles import _resolve_name


def test_existing_name_matched_case_insensitively():
    fam = {"profiles": {"balanced": {}}}
    assert _resolve_name(fam, "Balanced") == "balanced"
    assert _resolve_name(fam, "BALANCED") == "balanced"


def test_new_name_normalised_to_lowercase():
    fam = {"profiles": {"balanced": {}}}
    assert _resolve_name(fam, "  Fast  ") == "fast"


def test_odd_cased_existing_name_stays_addressable():
    # Pre-existing non-lowercase keys must remain deletable/renamable.
    fam = {"profiles": {"p40vBalanced": {}}}
    assert _resolve_name(fam, "p40vBalanced") == "p40vBalanced"
    assert _resolve_name(fam, "p40vbalanced") == "p40vBalanced"


def test_distinct_names_untouched():
    fam = {"profiles": {"balanced": {}, "p40v-balanced": {}}}
    assert _resolve_name(fam, "p40v-balanced") == "p40v-balanced"
