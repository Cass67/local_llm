"""Code prompts must not silently degrade to the easy cluster."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import model_router as mr  # noqa: E402

CODE_MSG = [{"role": "user", "content": "implement a retry decorator for the http client"}]


def _setup(*, hard_running: bool) -> None:
    mr._healthy_aliases = {"easy-model", "router"} | ({"hard-model"} if hard_running else set())
    mr._cluster_to_model = {"P40": "easy-model"} | (
        {"7900sv": "hard-model"} if hard_running else {}
    )
    mr._vision_aliases = set()
    mr.CLUSTER_REMAP = {}
    mr.RULES = [
        {"name": "code", "keywords": ["implement"], "cluster": "7900sv", "fallback": ["P40"]},
        {"name": "quick", "keywords": ["retry"], "cluster": "P40"},
        {"name": "search", "keywords": ["internet"], "cluster": "P40"},
    ]
    mr.DEFAULT_MODEL = "stale-alias-that-is-not-loaded"
    mr.DEFAULT_CLUSTER = "7900sv"


def test_code_prompt_uses_hard_cluster():
    _setup(hard_running=True)
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "hard-model", detail
    assert detail["reason"] == "rule", detail


def test_hard_cluster_down_uses_declared_fallback_not_later_rule():
    _setup(hard_running=False)
    detail = mr._route_detail(CODE_MSG)
    assert detail["model"] == "easy-model", detail
    # Must be an explicit fallback of the *code* rule, not the "quick" rule
    # winning by fall-through — that is how tiering silently inverted.
    assert detail["reason"] == "fallback", detail
    assert detail["rule"] == "code", detail


def test_stale_default_model_falls_back_to_default_cluster():
    _setup(hard_running=True)
    assert mr._route_detail([{"role": "user", "content": "hello there"}]) == {
        "model": "hard-model",
        "reason": "default",
    }


def test_easy_turn_does_not_pin_later_coding_turns():
    """Regression: an incidental search turn used to anchor the whole session.

    Taken verbatim from production logs — "…in internet…" matched the web-search
    rule first, so every following coding turn inherited the P40.
    """
    _setup(hard_running=True)
    convo = [
        {"role": "user", "content": "id like you to find actual crowd noise in internet"},
        {"role": "assistant", "content": "downloaded"},
        {"role": "user", "content": "implement into the game"},
    ]
    detail = mr._route_detail(convo)
    assert detail["model"] == "hard-model", detail


def test_easy_only_conversation_still_uses_easy_cluster():
    _setup(hard_running=True)
    convo = [{"role": "user", "content": "find actual crowd noise in internet"}]
    assert mr._route_detail(convo)["model"] == "easy-model"


def test_code_ref_signal_catches_unkeyworded_prompts():
    mr.RULES = [
        {"name": "code", "signals": ["has_code_ref"], "cluster": "7900sv"},
    ]
    mr._healthy_aliases = {"hard-model"}
    mr._cluster_to_model = {"7900sv": "hard-model"}
    mr._vision_aliases, mr.CLUSTER_REMAP = set(), {}
    mr.DEFAULT_MODEL = mr.DEFAULT_CLUSTER = None
    for prompt in (
        "port this to model_router.py",
        "why is `_route_detail` returning that",
        "update the file at /opt/local_llm/configs",
        "what does parse_args() do",
    ):
        assert mr._route_detail([{"role": "user", "content": prompt}])["model"] == "hard-model", (
            prompt
        )
    # Plain prose must not trip it.
    assert mr._route_detail([{"role": "user", "content": "how are you today"}])["reason"] == (
        "default"
    )


def test_router_alias_never_selected():
    _setup(hard_running=False)
    mr.DEFAULT_CLUSTER = None
    # sorted-first of {"easy-model", "router"} is "easy-model"; "router" is this
    # proxy itself and would loop back into the router.
    assert mr._route_detail([{"role": "user", "content": "hello there"}])["model"] != "router"


def test_hard_rules_have_no_substring_matched_keywords():
    """`_keyword_in` only word-bounds keywords that start AND end alphanumeric.

    Anything else is a raw substring match, which on a hard rule is a one-way
    trip: "go " (for Golang) fired on "go online for crowd noises" and, because
    difficulty ratchets, pinned the whole session to the hard cluster.
    """
    cfg = json.loads((Path(__file__).parent.parent / "configs" / "router_rules.json").read_text())
    loose = [
        (r["name"], k)
        for r in cfg["rules"]
        if r.get("cluster") == "7900sv"
        for k in r["keywords"]
        if not (k[-1:].isalnum() and k[:1].isalnum())
    ]
    assert not loose, loose


if __name__ == "__main__":
    test_code_prompt_uses_hard_cluster()
    test_hard_cluster_down_uses_declared_fallback_not_later_rule()
    test_stale_default_model_falls_back_to_default_cluster()
    test_easy_turn_does_not_pin_later_coding_turns()
    test_easy_only_conversation_still_uses_easy_cluster()
    test_code_ref_signal_catches_unkeyworded_prompts()
    test_router_alias_never_selected()
    test_hard_rules_have_no_substring_matched_keywords()
    print("ok")
