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
            "mtp": {
                "enabled": True,
                "draft_n_max": 3,
                "draft_n_min": 1,
                "draft_p_min": 0.5,
            },
        },
    }

    args = build_llama_server_args(metadata, port=8080)

    assert args == [
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
        "--spec-type",
        "draft-mtp",
        "--spec-draft-n-max",
        "3",
        "--spec-draft-n-min",
        "1",
        "--spec-draft-p-min",
        "0.5",
    ]


def test_build_llama_server_args_omits_legacy_raw_mtp_flags_when_structured_mtp_enabled():
    metadata = {
        "alias": "qwopus",
        "model_path": "/models/qwopus.gguf",
        "config": {
            "mtp": {"enabled": True, "draft_n_max": 3, "draft_n_min": 1, "draft_p_min": 0.5},
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
