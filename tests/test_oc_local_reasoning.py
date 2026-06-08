from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_oc_local_info_includes_reasoning_server_flag(tmp_path: Path):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    (accepted / "gemma-4-12b.json").write_text(
        json.dumps(
            {
                "family": "gemma-4-12b",
                "alias": "gemma-4-12b-it-qat-gguf",
                "model_name": "gemma-4-12b-it-qat-gguf",
                "repo": "unsloth/gemma-4-12B-it-qat-GGUF",
                "hf_repo": "unsloth/gemma-4-12B-it-qat-GGUF",
                "quant": "gemma-4-12B-it-qat-UD-Q4_K_XL",
                "hf_file": "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
                "remote_start": "./start24.sh",
                "profile": "balanced",
                "reasoning": True,
                "config": {
                    "ctx": 131072,
                    "batch": 4096,
                    "ubatch": 256,
                    "ngl": 999,
                    "backend": "vulkan",
                    "visible_devices": "0,1",
                    "split_mode": "layer",
                    "tensor_split": "1,1",
                    "reasoning": True,
                },
            }
        )
    )
    env = os.environ | {"LOCAL_LLM_RUNS_DIR": str(tmp_path)}

    result = subprocess.run(
        [
            "bash",
            "scripts/oc-local",
            "gemma-4-12b",
            "balanced",
            "--info",
            "--remote",
            "ubt26",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "reasoning=true" in result.stdout
    command_line = next(line for line in result.stdout.splitlines() if line.startswith("command="))
    assert "--reasoning on" in command_line


def test_oc_local_writes_per_model_reasoning_compat(tmp_path: Path):
    accepted = tmp_path / "accepted"
    accepted.mkdir(parents=True)
    (accepted / "gemma-4-12b.json").write_text(
        json.dumps(
            {
                "family": "gemma-4-12b",
                "alias": "gemma-4-12b-it-qat-gguf",
                "model_name": "gemma-4-12b-it-qat-gguf",
                "repo": "unsloth/gemma-4-12B-it-qat-GGUF",
                "hf_repo": "unsloth/gemma-4-12B-it-qat-GGUF",
                "quant": "gemma-4-12B-it-qat-UD-Q4_K_XL",
                "hf_file": "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
                "remote_start": "./start24.sh",
                "profile": "balanced",
                "reasoning": True,
                "config": {"ctx": 131072, "batch": 4096, "ubatch": 256, "ngl": 999},
            }
        )
    )
    pi_dir = tmp_path / "pi"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("ssh", "curl", "pi"):
        script = bin_dir / name
        script.write_text("#!/usr/bin/env bash\nexit 0\n")
        script.chmod(0o755)
    env = os.environ | {
        "LOCAL_LLM_RUNS_DIR": str(tmp_path),
        "PI_CODING_AGENT_DIR": str(pi_dir),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            "bash",
            "scripts/oc-local",
            "gemma-4-12b",
            "balanced",
            "--remote",
            "ubt26",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads((pi_dir / "models.json").read_text())
    models = data["providers"]["ubt26-llamacpp"]["models"]
    entry = next(item for item in models if item["id"] == "gemma-4-12b-it-qat-gguf")
    assert entry["reasoning"] is True
    assert entry["compat"] == {"supportsReasoningEffort": False}
