"""Tests for Docker runner control helpers."""

import json
from pathlib import Path
from unittest.mock import patch

from backend.runtime import DockerRunner, DockerRunnerConfig


def test_runner_launch_resolves_model_path_from_hf_cache(tmp_path):
    model = tmp_path / "models--Jackrong--Qwopus" / "snapshots" / "abc" / "model.gguf"
    model.parent.mkdir(parents=True)
    model.write_text("fake")
    metadata = {
        "alias": "qwopus",
        "hf_repo": "Jackrong/Qwopus",
        "hf_file": "model.gguf",
        "config": {"backend": "vulkan", "visible_devices": "0,1"},
    }
    host_models = tmp_path / "host-models"
    runner = DockerRunner(
        DockerRunnerConfig(image="runner:latest"), models_dir=tmp_path, host_models_dir=host_models
    )

    # _port_free probes the real host port; without this the test fails on any
    # machine that happens to have something bound to 8080.
    with patch.object(runner, "_port_free", return_value=True):
        with patch.object(runner, "_docker_json", return_value={}) as docker:
            runner.launch(metadata)

    create_call = next(
        call
        for call in docker.call_args_list
        if call.args[0] == "POST" and call.args[1].startswith("/containers/create")
    )
    create_payload = json.loads(create_call.args[2])
    assert create_payload["Cmd"][:5] == [
        "llama-server",
        "--port",
        "8080",
        "-m",
        str(model),
    ]
    assert create_payload["Image"] == "runner:latest"
    assert create_payload["HostConfig"]["NetworkMode"] == "host"
    assert create_payload["HostConfig"]["ShmSize"] == 1024 * 1024 * 1024
    assert create_payload["HostConfig"]["Binds"] == [f"{host_models}:/models:rw"]


def test_runner_is_running_reads_docker_state(tmp_path):
    runner = DockerRunner(DockerRunnerConfig(), models_dir=Path("/models"))
    with patch.object(
        runner,
        "_docker_json",
        return_value={"State": {"Running": True}},
    ):
        assert runner.is_running() is True
