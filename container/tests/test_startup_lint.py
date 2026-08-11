"""Boot-log scanning — silently-declined knobs must surface as warnings."""

from backend.startup_lint import scan_startup_log


def _ids(lines):
    return {f["id"] for f in scan_startup_log(lines)}


def test_clean_boot_log_is_silent():
    lines = [
        "llama_model_loader: loaded meta data with 30 key-value pairs",
        "load_tensors: offloading 48 repeating layers to GPU",
        "main: server is listening on http://0.0.0.0:8080",
    ]
    assert scan_startup_log(lines) == []


def test_cache_reuse_disabled_detected():
    lines = ["srv    load_model: cache_reuse is not supported by this context, will be disabled"]
    assert _ids(lines) == {"cache_reuse_disabled"}


def test_rccl_failure_detected():
    lines = ["ggml_backend_rocm: failed to initialize RCCL communicator, falling back"]
    assert _ids(lines) == {"rccl_unavailable"}


def test_cpu_fallback_detected():
    lines = ["ggml_vulkan: no usable GPU found, using CPU backend"]
    assert _ids(lines) == {"running_on_cpu"}


def test_each_issue_reported_once():
    lines = ["cache_reuse will be disabled"] * 5
    findings = scan_startup_log(lines)
    assert len(findings) == 1
    assert findings[0]["line"] == "cache_reuse will be disabled"


def test_multiple_distinct_issues_all_reported():
    lines = [
        "cache_reuse will be disabled",
        "llama_context: n_ctx_per_seq (8192) is less than n_ctx_train (262144)",
        "unknown argument: --spec-ngram-mod-n-match",
    ]
    assert _ids(lines) == {"cache_reuse_disabled", "ctx_below_trained", "unknown_argument"}


def test_long_lines_are_truncated():
    findings = scan_startup_log(["x" * 500 + " out of memory"])
    assert len(findings[0]["line"]) == 300
