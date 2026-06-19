"""Tests for project-owned Docker runner command generation."""

from backend.runtime import DockerRunnerConfig, build_llama_server_args, build_runner_container_spec


def test_build_llama_server_args_includes_model_runtime_and_mtp_flags():
    metadata = {
        "family": "qwopus",
        "alias": "qwopus-q5km",
        "model_path": "/models/models--Jackrong--Qwopus/snapshots/abc/qwopus.gguf",
        "config": {
            "ctx": 65536,
            "batch": 4096,
            "ubatch": 256,
            "ngl": 999,
            "split_mode": "layer",
            "tensor_split": "1,1",
            "reasoning": False,
            "context_shift": True,
            "cache_prompt": True,
            "cache_ram": 16384,
            "mtp_enabled": True,
            "mtp_draft_n_max": 3,
            "mtp_draft_n_min": 1,
            "mtp_draft_p_min": 0.5,
        },
    }

    args = build_llama_server_args(metadata, port=8080)

    assert args[:23] == [
        "llama-server",
        "--port",
        "8080",
        "-m",
        "/models/models--Jackrong--Qwopus/snapshots/abc/qwopus.gguf",
        "-ngl",
        "999",
        "--split-mode",
        "layer",
        "--tensor-split",
        "1,1",
        "-c",
        "65536",
        "-b",
        "4096",
        "-ub",
        "256",
        "--alias",
        "qwopus-q5km",
        "--reasoning",
        "off",
        "--context-shift",
        "--cache-prompt",
    ]
    assert "--spec-type" in args
    assert "draft-mtp" in args


def test_build_llama_server_args_emits_md_when_draft_model_configured():
    metadata = {
        "alias": "gemma4-mtp",
        "model_path": "/models/gemma4.gguf",
        "config": {
            "mtp_enabled": True,
            "mtp_draft_model": "/models/gemma4-assistant.gguf",
            "mtp_draft_n_max": 3,
            "mtp_draft_n_min": 1,
            "mtp_draft_p_min": 0.5,
        },
    }

    args = build_llama_server_args(metadata, port=8080)

    md_idx = args.index("-md")
    assert args[md_idx + 1] == "/models/gemma4-assistant.gguf"
    assert args.count("--spec-type") == 1
    assert "draft-mtp" in args


def test_build_llama_server_args_includes_repeat_penalties_when_configured():
    metadata = {
        "alias": "qwopus",
        "model_path": "/models/qwopus.gguf",
        "config": {"repeat_penalty": 1.05, "presence_penalty": 0.0},
    }

    args = build_llama_server_args(metadata, port=8080)

    assert args[args.index("--repeat-penalty") + 1] == "1.05"
    assert args[args.index("--presence-penalty") + 1] == "0.0"


def test_build_llama_server_args_can_disable_prompt_cache_for_swa_models():
    metadata = {
        "alias": "gemma4",
        "model_path": "/models/gemma.gguf",
        "config": {"cache_prompt": False, "ctx_checkpoints": 0, "context_shift": False},
    }

    args = build_llama_server_args(metadata, port=8080)

    assert "--cache-prompt" not in args
    assert args[args.index("--cache-ram") + 1] == "0"
    assert args[args.index("--ctx-checkpoints") + 1] == "0"
    assert "--checkpoint-min-step" not in args
    assert "--context-shift" not in args


def test_build_llama_server_args_omits_legacy_raw_mtp_flags_when_structured_mtp_enabled():
    metadata = {
        "alias": "qwopus",
        "model_path": "/models/qwopus.gguf",
        "config": {
            "mtp_enabled": True,
            "mtp_draft_n_max": 3,
            "mtp_draft_n_min": 1,
            "mtp_draft_p_min": 0.5,
            "flags": "--spec-type draft-mtp --spec-draft-n-max 3 --temp 0.6",
        },
    }

    args = build_llama_server_args(metadata, port=8080)

    assert args.count("--spec-type") == 1
    assert args.count("--spec-draft-n-max") == 1
    assert "--temp" in args


def test_build_runner_container_spec_uses_project_owned_runner_name_and_gpu_mounts():
    metadata = {
        "alias": "qwopus-q5km",
        "model_path": "/models/qwopus.gguf",
        "config": {"backend": "vulkan", "visible_devices": "0,1"},
    }
    config = DockerRunnerConfig(image="local-llm-runner:latest", port=8080)

    spec = build_runner_container_spec(metadata, config)

    assert spec.name == "local-llm-runner"
    assert spec.image == "local-llm-runner:latest"
    assert spec.ports == {"8080/tcp": 8080}
    assert spec.devices == ["/dev/kfd", "/dev/dri"]
    assert spec.group_add == ["991"]
    assert spec.environment["GGML_VK_VISIBLE_DEVICES"] == "0,1"
    assert spec.command[:3] == ["llama-server", "--port", "8080"]


def test_build_runner_container_spec_uses_nvidia_device_requests_for_cuda():
    metadata = {
        "alias": "qwopus-q5km",
        "model_path": "/models/qwopus.gguf",
        "config": {"backend": "cuda", "visible_devices": "0,1"},
    }
    config = DockerRunnerConfig(image="local-llm-runner-cuda:latest", port=8080)

    spec = build_runner_container_spec(metadata, config)

    assert spec.devices == []
    assert spec.group_add == []
    assert spec.device_requests == [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]
    assert spec.environment == {"CUDA_VISIBLE_DEVICES": "0,1"}
    assert "GGML_VK_VISIBLE_DEVICES" not in spec.environment
    assert "HIP_VISIBLE_DEVICES" not in spec.environment
