"""Project-owned runtime adapter primitives.

This module is intentionally pure for now: it builds llama-server args and a Docker
container spec from accepted metadata without touching Docker or live services.
"""

import http.client
import json
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DockerRunnerConfig:
    image: str = "local-llm-runner-rocm:latest"
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
    device_requests: list[dict[str, Any]] = field(default_factory=list)
    group_add: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    binds: list[str] = field(default_factory=list)


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
    if repo and filename:
        raise ValueError(f"model file not downloaded: {filename} (from {repo})")
    raise ValueError("accepted metadata missing model_path")


def _draft_path(metadata: dict[str, Any], models_dir: Path | None = None) -> str:
    cfg = _config(metadata)
    path = cfg.get("mtp_draft_model")
    if path:
        return str(path)
    repo = cfg.get("mtp_draft_hf_repo")
    filename = cfg.get("mtp_draft_hf_file")
    if repo and filename and models_dir:
        repo_dir = f"models--{str(repo).replace('/', '--')}"
        matches = sorted((models_dir / repo_dir / "snapshots").glob(f"*/{filename}"))
        if matches:
            return str(matches[-1])
    return ""


def _bool_flag(value: Any) -> str:
    return "on" if bool(value) else "off"


def build_llama_server_args(metadata: dict[str, Any], port: int) -> list[str]:  # noqa: C901
    """Build llama-server argv for a single accepted model."""
    cfg = _config(metadata)
    alias = str(metadata.get("alias") or metadata.get("family") or "local-llm-model")
    args = [
        "llama-server",
        "--port",
        str(port),
        "-m",
        _model_path(metadata),
    ]
    if cfg.get("ngl") is not None:
        args.extend(["-ngl", str(cfg["ngl"])])

    if cfg.get("split_mode"):
        args.extend(["--split-mode", str(cfg["split_mode"])])
    if cfg.get("tensor_split"):
        args.extend(["--tensor-split", str(cfg["tensor_split"])])

    ctx = cfg.get("ctx") or metadata.get("context")
    if ctx:
        args.extend(["-c", str(ctx)])
    if cfg.get("batch") is not None:
        args.extend(["-b", str(cfg["batch"])])
    if cfg.get("ubatch") is not None:
        args.extend(["-ub", str(cfg["ubatch"])])
    args.extend(["--alias", alias])
    reasoning = cfg.get("reasoning")
    if reasoning is None:
        reasoning = metadata.get("reasoning")
    if reasoning is not None:
        args.extend(["--reasoning", _bool_flag(reasoning)])
    # Cap thinking tokens; without it the budget defaults to unrestricted and the
    # model can waffle until it exhausts the context window. -1 = unrestricted.
    if cfg.get("reasoning_budget") is not None:
        args.extend(["--reasoning-budget", str(cfg["reasoning_budget"])])
    # Injected before the end-of-thinking tag when the budget runs out, so the
    # model transitions into a final answer instead of getting cut mid-thought.
    if cfg.get("reasoning_budget_message"):
        args.extend(["--reasoning-budget-message", str(cfg["reasoning_budget_message"])])

    if cfg.get("context_shift"):
        args.append("--context-shift")
    # Always emit --cache-ram so the profile is authoritative; omitting it lets
    # llama-server fall back to its built-in RAM cache default, overriding "off".
    if cfg.get("cache_prompt"):
        args.append("--cache-prompt")
    args.extend(["--cache-ram", str(cfg.get("cache_ram") or 0)])
    # Always emit --ctx-checkpoints so the profile is authoritative; omitting it
    # lets llama-server fall back to its built-in default (32), overriding "off".
    ctx_chk = int(cfg.get("ctx_checkpoints") or 0)
    if ctx_chk > 0:
        args.extend(["--ctx-checkpoints", str(ctx_chk)])
        # The ROCmFPX fork renamed --checkpoint-min-step to --checkpoint-every-n-tokens
        # and rejects the stock flag; emit the fork's name on rocmfp4.
        if cfg.get("checkpoint_min_step") is not None:
            flag = (
                "--checkpoint-every-n-tokens"
                if cfg.get("backend") == "rocmfp4"
                else "--checkpoint-min-step"
            )
            args.extend([flag, str(cfg["checkpoint_min_step"])])
    else:
        args.extend(["--ctx-checkpoints", "0"])
    # Cheap KV-shift reuse across small prefix mismatches (e.g. per-turn tail
    # re-render under MTP spec); recovers cache hits when cache-ram/checkpoints
    # are off for VRAM. 0 disables.
    if cfg.get("cache_reuse") is not None:
        args.extend(["--cache-reuse", str(cfg["cache_reuse"])])
    if cfg.get("repeat_penalty") is not None:
        args.extend(["--repeat-penalty", str(cfg["repeat_penalty"])])
    if cfg.get("presence_penalty") is not None:
        args.extend(["--presence-penalty", str(cfg["presence_penalty"])])
    if cfg.get("frequency_penalty") is not None:
        args.extend(["--frequency-penalty", str(cfg["frequency_penalty"])])

    if cfg.get("timeout") is not None:
        args.extend(["--timeout", str(cfg["timeout"])])
    if cfg.get("threads_http") is not None:
        args.extend(["--threads-http", str(cfg["threads_http"])])
    if cfg.get("parallel") is not None:
        args.extend(["--parallel", str(cfg["parallel"])])
    if cfg.get("no_cont_batching"):
        args.append("--no-cont-batching")
    if cfg.get("prio") is not None:
        args.extend(["--prio", str(cfg["prio"])])
    if cfg.get("no_warmup"):
        args.append("--no-warmup")

    if cfg.get("mtp_enabled"):
        draft_path = cfg.get("mtp_draft_model")
        if draft_path:
            args.extend(["-md", str(draft_path)])
        # draft-mtp (self-speculation) by default; Laguna's DFlash draft uses
        # draft-dflash. Both drive the same -md + --spec-draft-n-* plumbing.
        args.extend(["--spec-type", str(cfg.get("spec_type") or "draft-mtp")])
        if cfg.get("mtp_draft_n_max") is not None:
            args.extend(["--spec-draft-n-max", str(cfg["mtp_draft_n_max"])])
        if cfg.get("mtp_draft_n_min") is not None:
            args.extend(["--spec-draft-n-min", str(cfg["mtp_draft_n_min"])])
        if cfg.get("mtp_draft_p_min") is not None:
            args.extend(["--spec-draft-p-min", str(cfg["mtp_draft_p_min"])])

    if cfg.get("temperature") is not None:
        args.extend(["--temp", str(cfg["temperature"])])
    if cfg.get("top_p") is not None:
        args.extend(["--top-p", str(cfg["top_p"])])
    if cfg.get("top_k") is not None:
        args.extend(["--top-k", str(cfg["top_k"])])
    if cfg.get("min_p") is not None:
        args.extend(["--min-p", str(cfg["min_p"])])
    if cfg.get("repetition_penalty") is not None:
        args.extend(["--repeat-penalty", str(cfg["repetition_penalty"])])

    if cfg.get("cache_type_k") is not None:
        args.extend(["--cache-type-k", str(cfg["cache_type_k"])])
    if cfg.get("cache_type_v") is not None:
        args.extend(["--cache-type-v", str(cfg["cache_type_v"])])

    if cfg.get("flash_attention"):
        args.extend(["-fa", "on"])
    if cfg.get("jinja"):
        args.append("--jinja")

    if cfg.get("mmproj"):
        args.extend(["--mmproj", str(cfg["mmproj"])])
    if cfg.get("no_mmap"):
        args.append("--no-mmap")
    if cfg.get("mlock"):
        args.append("--mlock")
    if cfg.get("no_kv_offload"):
        args.append("--no-kv-offload")
    if cfg.get("numa"):
        args.extend(["--numa", str(cfg["numa"])])
    if cfg.get("main_gpu") is not None:
        args.extend(["--main-gpu", str(cfg["main_gpu"])])
    if cfg.get("threads") is not None:
        args.extend(["-t", str(cfg["threads"])])
    if cfg.get("threads_batch") is not None:
        args.extend(["-tb", str(cfg["threads_batch"])])

    # Strip known-promoted flags from raw flags so they're not doubled
    _PROMOTED_FLAGS = {  # noqa: N806
        "-fa",
        "--flash-attn",
        "--jinja",
        "-md",
        "--model-draft",
        "--spec-type",
        "--spec-draft-n-max",
        "--spec-draft-n-min",
        "--spec-draft-p-min",
        "--parallel",
        "--cache-ram",
        "--cache-reuse",
        "--reasoning-budget",
        "--reasoning-budget-message",
        "--mmproj",
    }
    raw_tokens = str(cfg.get("flags") or "").split()
    filtered: list[str] = []
    skip_next = False
    for tok in raw_tokens:
        if skip_next:
            skip_next = False
            continue
        if tok in _PROMOTED_FLAGS:
            skip_next = True
            continue
        if tok in ("on", "off") and filtered and filtered[-1] in ("-fa", "--flash-attn"):
            filtered.pop()
            continue
        filtered.append(tok)
    args.extend(filtered)
    return args


def build_runner_container_spec(  # noqa: C901
    metadata: dict[str, Any], config: DockerRunnerConfig, models_dir: Path | None = None
) -> DockerContainerSpec:
    """Build a Docker container spec for the project-owned runner."""
    if models_dir:
        if not (metadata.get("model_path") or metadata.get("path")):
            metadata = {**metadata, "model_path": _model_path(metadata, models_dir)}
        cfg = _config(metadata)
        if cfg.get("mtp_enabled") and not cfg.get("mtp_draft_model"):
            draft_path = _draft_path(metadata, models_dir)
            if draft_path:
                merged_cfg = {**cfg, "mtp_draft_model": draft_path}
                metadata = {**metadata, "config": merged_cfg}
    cfg = _config(metadata)
    backend = str(cfg.get("backend") or "rocm")
    visible_devices = str(cfg.get("visible_devices") or "")
    environment: dict[str, str] = {}
    devices: list[str] = []
    device_requests: list[dict[str, Any]] = []
    group_add: list[str] = []
    binds: list[str] = []

    if backend == "cuda":
        device_requests = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]
        if visible_devices:
            environment["CUDA_VISIBLE_DEVICES"] = visible_devices
    elif backend == "mixed_vulkan" or cfg.get("mixed_vulkan"):
        # backend "mixed_vulkan", or a laguna cluster spanning both AMD+NVIDIA
        # (flagged via cfg["mixed_vulkan"] in _build_launch_metadata).
        # AMD + NVIDIA in one container: AMD devices + NVIDIA runtime.
        # Bind-mount host NVIDIA graphics libs so libEGL_nvidia.so.0 (headless Vulkan ICD)
        # can initialize — the container runtime doesn't inject them with gpu+graphics caps.
        devices = ["/dev/kfd", "/dev/dri", "/dev/nvidia-modeset"]
        group_add = [config.render_group]
        device_requests = [
            {"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu", "graphics", "utility"]]}
        ]
        _nlib = "/host/nvidia-libs"  # host lib dir mounted read-only into mgmt container
        _glx_patterns = [
            "libGLX_nvidia.so.*",
            "libnvidia-glcore.so.*",
            "libnvidia-glsi.so.*",
            "libnvidia-gpucomp.so.*",
            "libnvidia-tls.so.*",
            "libnvidia-glvkspirv.so.*",
            "libnvidia-present.so.*",
        ]
        import glob as _glob

        _nvidia_libs = [
            f
            for pat in _glx_patterns
            for f in _glob.glob(f"{_nlib}/{pat}")
            if ".so." in f.split("/")[-1]
        ]
        binds = [
            *[
                f"/usr/lib/x86_64-linux-gnu/{name}:/usr/lib/x86_64-linux-gnu/{name}:ro"
                for lib in _nvidia_libs
                for name in (lib.split("/")[-1],)
            ],
        ]
        environment["VK_ICD_FILENAMES"] = (
            "/usr/share/vulkan/icd.d/nvidia_egl_icd.json:/usr/share/vulkan/icd.d/radeon_icd.json"
        )
        if visible_devices:
            environment["GGML_VK_VISIBLE_DEVICES"] = visible_devices
    elif cfg.get("nvidia_vulkan"):
        # NVIDIA GPU on Vulkan backend: inject via nvidia container runtime.
        # Use the headless EGL ICD baked into the image (libEGL_nvidia.so.0).
        # "compute" is required: without it the runtime omits libnvidia-gpucomp.so and
        # the Vulkan ICD fails to init ("no usable GPU"), silently falling back to CPU.
        device_requests = [
            {
                "Driver": "nvidia",
                "Count": -1,
                "Capabilities": [["gpu", "graphics", "compute", "utility"]],
            }
        ]
        environment["VK_ICD_FILENAMES"] = "/usr/share/vulkan/icd.d/nvidia_egl_icd.json"
        if visible_devices:
            environment["GGML_VK_VISIBLE_DEVICES"] = visible_devices
    else:
        devices = ["/dev/kfd", "/dev/dri"]
        group_add = [config.render_group]
        if backend in ("vulkan", "laguna"):
            # AMD-only Vulkan/laguna: pin the radeon ICD so only Mesa RADV enumerates.
            # The image also ships the NVIDIA ICD (present but non-functional here — no
            # libs injected) and lavapipe (CPU software); either could otherwise perturb
            # GGML's Vulkan device order or add a phantom device. Set unconditionally —
            # independent of visible_devices, which is empty when the inventory has no
            # vulkan_index for these cards.
            environment["VK_ICD_FILENAMES"] = "/usr/share/vulkan/icd.d/radeon_icd.json"
            if visible_devices:
                environment["GGML_VK_VISIBLE_DEVICES"] = visible_devices
        elif visible_devices:
            environment["HIP_VISIBLE_DEVICES"] = visible_devices

    return DockerContainerSpec(
        name=config.name,
        image=config.image,
        command=build_llama_server_args(metadata, port=config.port),
        ports={f"{config.port}/tcp": config.port},
        devices=devices,
        device_requests=device_requests,
        group_add=group_add,
        environment=environment,
        binds=binds,
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

    def _port_free(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", self.config.port))
                return False
            except OSError:
                return True

    def launch(self, metadata: dict[str, Any]) -> None:
        self.stop()
        deadline = time.monotonic() + 8.0
        while not self._port_free():
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"port {self.config.port} is still occupied after stopping the runner container — "  # noqa: E501
                    "a native llama-server process is likely running on the host; "
                    f"stop it before switching models (kill $(lsof -ti :{self.config.port}))"
                )
            time.sleep(0.25)
        spec = build_runner_container_spec(metadata, self.config, self.models_dir)
        env = [f"{key}={value}" for key, value in spec.environment.items()]
        binds = [f"{self.host_models_dir}:/models:rw"] + spec.binds
        host_config: dict[str, Any] = {
            "NetworkMode": "host",
            "Binds": binds,
            "Devices": [
                {"PathOnHost": device, "PathInContainer": device, "CgroupPermissions": "rwm"}
                for device in spec.devices
            ],
            "GroupAdd": spec.group_add,
        }
        if spec.device_requests:
            host_config["DeviceRequests"] = spec.device_requests
        payload = {
            "Image": spec.image,
            "Cmd": spec.command,
            "Env": env,
            "HostConfig": host_config,
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

        return _docker_logs_tail(lines, self.config.name)
