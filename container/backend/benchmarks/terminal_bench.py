"""Terminal-Bench runner: drives the real terminal-bench CLI against a model endpoint."""

import json
import os
import re
import subprocess  # noqa: S404 # nosec B404
import sys
import time
from pathlib import Path
from typing import Any

from .base import BaseBenchmarkRunner

_STATE_DIR = Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state"))
_RUNS_DIR = _STATE_DIR / "runs" / "benchmarks" / "terminal_bench"


class TerminalBenchRunner(BaseBenchmarkRunner):
    """Runs the actual Terminal-Bench harness against an OpenAI-compatible endpoint."""

    @property
    def name(self) -> str:
        return "terminal-bench"

    def validate(self, req: dict[str, Any]) -> list[str]:
        errors = []
        if not req.get("endpoint_id"):
            errors.append("endpoint_id is required")
        if not req.get("model"):
            errors.append("model is required")
        return errors

    def list_tasks(self) -> list[str]:
        from terminal_bench.dataset.dataset import Dataset

        dataset_name = os.environ.get("TERMINAL_BENCH_DATASET_NAME", "terminal-bench-core")
        dataset_version = os.environ.get("TERMINAL_BENCH_DATASET_VERSION", "0.1.1")
        return sorted(Dataset(name=dataset_name, version=dataset_version).task_ids)

    def run(
        self,
        endpoint_id: int,
        model: str,
        prompt_text: str,
        **kwargs,
    ) -> dict[str, Any]:
        endpoint_name = kwargs.get("endpoint_name", "terminal-bench")
        endpoint_base_url = kwargs.get("endpoint_base_url", "")
        dataset_name = os.environ.get("TERMINAL_BENCH_DATASET_NAME", "terminal-bench-core")
        dataset_version = os.environ.get("TERMINAL_BENCH_DATASET_VERSION", "0.1.1")
        task_id = prompt_text.strip() or None
        run_all = task_id == "__all__"
        first_n_match = re.match(r"^__first_(\d+)__$", task_id or "")
        run_first_n = int(first_n_match.group(1)) if first_n_match else None
        run_batch = run_all or run_first_n is not None
        if run_batch:
            task_id = None

        run_id = kwargs.get("run_id") or f"web-{int(time.time())}"
        # Our run_dir holds run.log for the live console. tb gets its own nested dir
        # (tb_run_dir) so it doesn't see our pre-created dir and mistake it for a resume
        # (which fails on the missing lock file). run_id stays in the cmdline/container
        # names so _cancel_run still matches.
        run_dir = _RUNS_DIR / run_id
        tb_run_dir = run_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        quiet_code = (
            "import logging; logging.disable(logging.INFO); "
            "from terminal_bench.cli.tb.main import app; app()"
        )
        cmd = [
            sys.executable,
            "-c",
            quiet_code,
            "run",
            "--dataset-name",
            dataset_name,
            "--dataset-version",
            dataset_version,
            "--agent",
            "terminus-2",
            "--model",
            f"openai/{model}",
            "--n-concurrent",
            "4" if run_batch else "1",
            "--output-path",
            str(run_dir),
            "--run-id",
            run_id,
        ]
        if run_all:
            pass  # no --task-id / --n-tasks limit: runs every task in the dataset
        elif run_first_n is not None:
            cmd += ["--n-tasks", str(run_first_n)]
        elif task_id:
            cmd += ["--task-id", task_id]
        else:
            cmd += ["--n-tasks", "1"]

        env = {
            **os.environ,
            "OPENAI_API_BASE": endpoint_base_url,
            "OPENAI_API_KEY": kwargs.get("api_key") or "local-llm",
            "PYTHONUNBUFFERED": "1",  # flush tb output to run.log live so the UI console tails it
        }

        start_time = time.perf_counter()
        status = "ok"
        error = None
        response_text = ""
        prompt_tokens = None
        completion_tokens = None

        log_path = run_dir / "run.log"

        try:
            with log_path.open("w") as log_f:
                proc = subprocess.run(  # noqa: S603 # nosec B603
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    timeout=21600 if run_batch else 1800,
                    env=env,
                    check=False,
                )
            log_tail = log_path.read_text()[-4000:] if log_path.exists() else ""
            results_path = tb_run_dir / "results.json"
            metadata_path = tb_run_dir / "run_metadata.json"

            if results_path.exists() and metadata_path.exists():
                results = json.loads(results_path.read_text())
                metadata = json.loads(metadata_path.read_text())
                trials = results.get("results", [])
                resolved = sum(1 for t in trials if t.get("is_resolved"))
                prompt_tokens = sum(t.get("total_input_tokens") or 0 for t in trials) or None
                completion_tokens = sum(t.get("total_output_tokens") or 0 for t in trials) or None
                accuracy = metadata.get("accuracy")
                response_text = f"{resolved}/{len(trials)} tasks resolved" + (
                    f" (accuracy={accuracy:.2f})" if accuracy is not None else ""
                )
                if proc.returncode != 0 and not trials:
                    status = "error"
                    error = log_tail or "tb run failed"
            else:
                status = "error"
                error = log_tail or "tb run produced no results"
        except subprocess.TimeoutExpired:
            status = "error"
            error = "terminal-bench run timed out"
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
