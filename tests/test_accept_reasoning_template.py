from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_accept_defaults_reasoning_on_in_metadata_and_profiles(tmp_path: Path):
    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            {
                "repo": "Example/Gemma-GGUF",
                "family": "gemma-test",
                "alias": "gemma-test",
                "target": "remote:ubt26",
                "profile": "balanced",
                "load_status": "success",
                "ctx": 131072,
                "batch": 4096,
                "ubatch": 256,
                "ngl": 999,
                "prompt_tok_s": 50.0,
                "decode_tok_s": 12.0,
                "prompt_tokens": 64,
                "decode_tokens": 128,
                "quant": "Q4_K_M",
                "hf_file": "model.gguf",
                "backend": "vulkan",
                "visible_devices": "0,1",
                "split_mode": "layer",
                "tensor_split": "1,1",
            }
        )
    )
    env = os.environ | {"LOCAL_LLM_RUNS_DIR": str(tmp_path / "runs")}

    result = subprocess.run(
        ["bash", "scripts/model-manager.sh", "accept", str(bench)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / "runs" / "accepted" / "gemma-test.json").read_text())
    assert data["reasoning"] is True
    assert data["config"]["reasoning"] is True
    assert all(profile["reasoning"] is True for profile in data["profiles"].values())
    launcher = Path(data["launcher_file"]).read_text()
    assert "--reasoning on" in launcher


def test_accept_rejects_weak_benchmark_metrics(tmp_path: Path):
    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            {
                "repo": "Example/TooBig-GGUF",
                "family": "too-big",
                "alias": "too-big",
                "target": "remote:ubt26",
                "profile": "balanced",
                "load_status": "success",
                "ctx": 131072,
                "batch": 4096,
                "ubatch": 256,
                "ngl": 999,
                "prompt_tok_s": 17.89,
                "decode_tok_s": 4.23,
                "prompt_tokens": 17,
                "decode_tokens": 32,
                "quant": "Q6_K",
                "hf_file": "model.gguf",
                "backend": "vulkan",
                "visible_devices": "0,1",
                "split_mode": "layer",
                "tensor_split": "1,1",
            }
        )
    )
    env = os.environ | {"LOCAL_LLM_RUNS_DIR": str(tmp_path / "runs")}

    result = subprocess.run(
        ["bash", "scripts/model-manager.sh", "accept", str(bench)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode != 0
    assert "below acceptance threshold" in result.stderr
