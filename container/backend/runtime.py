"""Project-owned runtime adapter primitives.

This module is intentionally pure for now: it builds llama-server args and a Docker
container spec from accepted metadata without touching Docker or live services.
"""

import http.client
import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DockerRunnerConfig:
    image: str = "local-llm-runner:latest"
    name: str = "local-llm-runner"
    port: int = 8080
    render_group: str = "991"
    socket_path: Path = Path("/var/run/docker.sock")


@dataclass(frozen=True)
class DockerContainerSpec:
    name: str
    image: str
    command: list[str]
    ports: dict[str, int]
    devices: list[str] = field(default_factory=list)
    group_add: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)


def _config(metadata: dict[str, Any]) -> dict[str, Any]:
    value = metadata.get("config")
    return value if isinstance(value, dict) else {}


def _model_path(metadata: dict[str, Any], models_dir: Path | None = None) -> str:
    path = metadata.get("model_path") or metadata.get("path")
    if path:
        return str(path)
    repo = metadata.get("hf_repo") or metadata.get("repo")
    filename = metadata.get("hf_file")
    if repo and filename and models_dir:
        repo_dir = f"models--{str(repo).replace('/', '--')}"
        matches = sorted((models_dir / repo_dir / "snapshots").glob(f"*/{filename}"))
        if matches:
            return str(matches[-1])
    raise ValueError("accepted metadata missing model_path")


def _bool_flag(value: Any) -> str:
    return "on" if bool(value) else "off"


def build_llama_server_args(metadata: dict[str, Any], port: int) -> list[str]:
    """Build llama-server argv for a single accepted model."""
    cfg = _config(metadata)
    alias = str(metadata.get("alias") or metadata.get("family") or "local-llm-model")
    args = [
        "llama-server",
        "--port",
        str(port),
        "-m",
        _model_path(metadata),
        "-ngl",
        str(cfg.get("ngl", 999)),
    ]

    if cfg.get("split_mode"):
        args.extend(["--split-mode", str(cfg["split_mode"])])
    if cfg.get("tensor_split"):
        args.extend(["--tensor-split", str(cfg["tensor_split"])])

    args.extend(
        [
            "-c",
            str(cfg.get("ctx") or metadata.get("context") or 65536),
            "-b",
            str(cfg.get("batch", 4096)),
            "-ub",
            str(cfg.get("ubatch", 256)),
            "--alias",
            alias,
            "--reasoning",
            _bool_flag(cfg.get("reasoning", metadata.get("reasoning", False))),
        ]
    )

    mtp = cfg.get("mtp")
    if isinstance(mtp, dict) and mtp.get("enabled"):
        args.extend(
            [
                "--spec-type",
                "draft-mtp",
                "--spec-draft-n-max",
                str(mtp.get("draft_n_max", 3)),
                "--spec-draft-n-min",
                str(mtp.get("draft_n_min", 1)),
                "--spec-draft-p-min",
                str(mtp.get("draft_p_min", 0.5)),
            ]
        )

    raw_flags = str(cfg.get("flags") or "").split()
    if isinstance(mtp, dict) and mtp.get("enabled"):
        mtp_flags = {
            "--spec-type",
            "--spec-draft-n-max",
            "--spec-draft-n-min",
            "--spec-draft-p-min",
        }
        filtered_flags: list[str] = []
        skip_next = False
        for flag in raw_flags:
            if skip_next:
                skip_next = False
                continue
            if flag in mtp_flags:
                skip_next = True
                continue
            filtered_flags.append(flag)
        raw_flags = filtered_flags
    args.extend(raw_flags)
    return args


def build_runner_container_spec(
    metadata: dict[str, Any], config: DockerRunnerConfig, models_dir: Path | None = None
) -> DockerContainerSpec:
    """Build a Docker container spec for the project-owned runner."""
    if models_dir and not (metadata.get("model_path") or metadata.get("path")):
        metadata = {**metadata, "model_path": _model_path(metadata, models_dir)}
    cfg = _config(metadata)
    visible_devices = str(cfg.get("visible_devices") or "")
    environment: dict[str, str] = {}
    if visible_devices:
        environment["GGML_VK_VISIBLE_DEVICES"] = visible_devices
        environment["HIP_VISIBLE_DEVICES"] = visible_devices
        environment["ROCR_VISIBLE_DEVICES"] = visible_devices

    return DockerContainerSpec(
        name=config.name,
        image=config.image,
        command=build_llama_server_args(metadata, port=config.port),
        ports={f"{config.port}/tcp": config.port},
        devices=["/dev/kfd", "/dev/dri"],
        group_add=[config.render_group],
        environment=environment,
    )


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(self.socket_path))


class DockerRunner:
    def __init__(
        self, config: DockerRunnerConfig, models_dir: Path, host_models_dir: Path | None = None
    ):
        self.config = config
        self.models_dir = models_dir
        self.host_models_dir = host_models_dir or models_dir

    def _docker_json(self, method: str, path: str, body: str | None = None) -> dict[str, Any]:
        conn = _UnixHTTPConnection(self.config.socket_path)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            if response.status == 404:
                return {}
            if response.status >= 400:
                raise RuntimeError(f"docker {method} {path} failed: HTTP {response.status}")
            if not data:
                return {}
            return json.loads(data.decode("utf-8"))
        finally:
            conn.close()

    def stop(self) -> None:
        self._docker_json("POST", f"/containers/{self.config.name}/stop?t=30")
        self._docker_json("DELETE", f"/containers/{self.config.name}?force=true")

    def launch(self, metadata: dict[str, Any]) -> None:
        self.stop()
        spec = build_runner_container_spec(metadata, self.config, self.models_dir)
        env = [f"{key}={value}" for key, value in spec.environment.items()]
        payload = {
            "Image": spec.image,
            "Cmd": spec.command,
            "Env": env,
            "HostConfig": {
                "NetworkMode": "host",
                "Binds": [f"{self.host_models_dir}:/models:rw"],
                "Devices": [
                    {"PathOnHost": device, "PathInContainer": device, "CgroupPermissions": "rwm"}
                    for device in spec.devices
                ],
                "GroupAdd": spec.group_add,
            },
        }
        self._docker_json(
            "POST", f"/containers/create?name={self.config.name}", json.dumps(payload)
        )
        self._docker_json("POST", f"/containers/{self.config.name}/start")

    def is_running(self) -> bool:
        data = self._docker_json("GET", f"/containers/{self.config.name}/json")
        state = data.get("State") if isinstance(data, dict) else None
        return bool(isinstance(state, dict) and state.get("Running"))

    def logs(self, lines: int = 80) -> list[str]:
        # Imported lazily to avoid a module cycle with log_stream.
        from .log_stream import _docker_logs_tail

        return _docker_logs_tail(lines)
