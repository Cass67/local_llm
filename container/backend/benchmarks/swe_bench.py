"""SWE-bench runner: uses the real mini-swe-agent to generate patches, then the actual
swebench evaluation harness to score them."""

import json
import logging
import os
import re
import subprocess  # noqa: S404 # nosec B404
import sys
import time
from pathlib import Path
from typing import Any

from .base import BaseBenchmarkRunner

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("datasets").setLevel(logging.WARNING)

_STATE_DIR = Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state"))
_RUNS_DIR = _STATE_DIR / "runs" / "benchmarks" / "swe_bench"


class SwebenchRunner(BaseBenchmarkRunner):
    """Runs the real mini-swe-agent against an OpenAI-compatible endpoint, then scores the
    resulting patch(es) with the actual swebench evaluation harness."""

    @property
    def name(self) -> str:
        return "swe-bench"

    def validate(self, req: dict[str, Any]) -> list[str]:
        errors = []
        if not req.get("endpoint_id"):
            errors.append("endpoint_id is required")
        if not req.get("model"):
            errors.append("model is required")
        return errors

    def list_tasks(self) -> list[str]:
        from datasets import load_dataset

        dataset_name = os.environ.get("SWE_BENCH_DATASET_NAME", "princeton-nlp/SWE-bench_Lite")
        split = os.environ.get("SWE_BENCH_SPLIT", "test")
        dataset = load_dataset(dataset_name, split=split)  # nosec B615
        return sorted(dataset["instance_id"])

    def run(
        self,
        endpoint_id: int,
        model: str,
        prompt_text: str,
        **kwargs,
    ) -> dict[str, Any]:
        endpoint_name = kwargs.pop("endpoint_name", "swe-bench")
        endpoint_base_url = kwargs.pop("endpoint_base_url", "")
        dataset_name = os.environ.get("SWE_BENCH_DATASET_NAME", "princeton-nlp/SWE-bench_Lite")
        split = os.environ.get("SWE_BENCH_SPLIT", "test")
        instance_id_filter = prompt_text.strip() or None
        run_all = instance_id_filter == "__all__"

        run_id = kwargs.get("run_id") or f"web-{int(time.time())}"
        run_dir = _RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "run.log"

        start_time = time.perf_counter()
        status = "ok"
        error = None
        response_text = ""
        prompt_tokens = None
        completion_tokens = None

        try:
            target_instance_id = None
            if not run_all:
                target_instance_id = instance_id_filter
                if target_instance_id is None:
                    from datasets import load_dataset

                    dataset = load_dataset(dataset_name, split=split)  # nosec B615
                    target_instance_id = sorted(dataset["instance_id"])[0]

            workers = os.environ.get("SWE_BENCH_MAX_WORKERS", "4" if run_all else "1")
            env = {
                **os.environ,
                "OPENAI_API_BASE": endpoint_base_url,
                "OPENAI_API_KEY": kwargs.get("api_key") or "local-llm",
                "MSWEA_COST_TRACKING": "ignore_errors",
            }
            agent_cmd = [
                sys.executable,
                "-m",
                "minisweagent.run.benchmarks.swebench",
                "--subset",
                dataset_name,
                "--split",
                split,
                "-m",
                f"openai/{model}",
                "-o",
                str(run_dir),
                "-w",
                workers,
            ]
            if target_instance_id:
                agent_cmd += ["--filter", f"^{re.escape(target_instance_id)}$"]

            log_path.write_text("running mini-swe-agent to generate patch(es)...\n")
            with log_path.open("a") as log_f:
                log_f.flush()
                agent_proc = subprocess.run(  # noqa: S603 # nosec B603
                    agent_cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    timeout=21600 if run_all else 1800,
                    env=env,
                    check=False,
                )

            predictions_path = run_dir / "preds.json"
            if not predictions_path.exists():
                raise RuntimeError(
                    f"mini-swe-agent produced no predictions (exit {agent_proc.returncode})"
                )

            with log_path.open("a") as log_f:
                log_f.write("running evaluation harness...\n")
                log_f.flush()
                quiet_code = (
                    "import logging; logging.disable(logging.INFO); "
                    "import runpy; "
                    "runpy.run_module('swebench.harness.run_evaluation', run_name='__main__')"
                )
                harness_cmd = [
                    sys.executable,
                    "-c",
                    quiet_code,
                    "--predictions_path",
                    str(predictions_path),
                    "--dataset_name",
                    dataset_name,
                    "--split",
                    split,
                    "--run_id",
                    run_id,
                    "--max_workers",
                    workers,
                    "--report_dir",
                    str(run_dir),
                ]
                if target_instance_id:
                    harness_cmd += ["--instance_ids", target_instance_id]
                harness_proc = subprocess.run(  # noqa: S603 # nosec B603
                    harness_cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    timeout=21600 if run_all else 1800,
                    cwd=run_dir,
                    check=False,
                )

            report_path = run_dir / f"{model.replace('/', '__')}.{run_id}.json"
            if report_path.exists():
                report = json.loads(report_path.read_text())
                resolved = report.get("resolved_instances", 0)
                total = report.get("submitted_instances", 1)
                response_text = f"{resolved}/{total} instances resolved"
                if resolved == 0 and report.get("error_instances", 0) > 0:
                    status = "error"
                    error = f"instance errored during evaluation: {report.get('error_ids')}"
            else:
                status = "error"
                tail = log_path.read_text()[-4000:] if log_path.exists() else ""
                error = tail or (
                    f"swebench harness produced no report (exit {harness_proc.returncode})"
                )
        except Exception as e:  # noqa: BLE001
            status = "error"
            error = str(e)

        duration_ms = (time.perf_counter() - start_time) * 1000
        duration_seconds = max(duration_ms / 1000, 0.001)
        total_tokens = (
            (prompt_tokens or 0) + (completion_tokens or 0)
            if prompt_tokens or completion_tokens
            else None
        )
        return {
            "endpoint_id": endpoint_id,
            "endpoint_name": endpoint_name,
            "endpoint_base_url": endpoint_base_url,
            "model": model,
            "prompt_text": prompt_text,
            "response_text": response_text,
            "latency_ms": duration_ms,
            "duration_ms": duration_ms,
            "output_chars": len(response_text),
            "output_words": len(response_text.split()),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "throughput_tps": completion_tokens / duration_seconds if completion_tokens else None,
            "throughput_cps": len(response_text) / duration_seconds if response_text else None,
            "status": status,
            "error": error,
        }
