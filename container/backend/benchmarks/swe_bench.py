"""SWE-bench runner: uses the real mini-swe-agent to generate patches, then the actual
swebench evaluation harness to score them."""

import json
import logging
import os
import re
import shutil
import subprocess  # noqa: S404 # nosec B404
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from .base import BaseBenchmarkRunner

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("datasets").setLevel(logging.WARNING)

_STATE_DIR = Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state"))
_RUNS_DIR = _STATE_DIR / "runs" / "benchmarks" / "swe_bench"


@contextmanager
def _background_image_pruner(log_path: Path, interval_sec: float = 120.0):
    """Periodically remove unused Docker images while a full-dataset run is in progress.

    Each SWE-bench instance uses its own multi-GB image, and cleanup normally only
    happens once at the very end of the harness run — for a 300-instance run that means
    peak disk usage holds every image simultaneously, which can fill the disk long before
    the run finishes. `docker image prune` only removes images with no container
    referencing them, so already-finished instances (whose --rm containers already exited)
    are safe to reclaim without touching instances still in progress.
    """
    stop_event = threading.Event()

    def _loop() -> None:
        while not stop_event.wait(interval_sec):
            docker_bin = shutil.which("docker") or "docker"
            # only prune fully-built, unreferenced images — never build cache. Pruning
            # build cache mid-run can delete layers an in-progress `docker build` for a
            # different instance is actively using, corrupting that build (observed as
            # spurious "No such image" 404s on otherwise-healthy instances).
            cmd = [docker_bin, "image", "prune", "-af"]
            try:
                proc = subprocess.run(  # noqa: S603 # nosec B603
                    cmd, capture_output=True, text=True, timeout=120, check=False
                )
                reclaimed = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
                with log_path.open("a") as log_f:
                    log_f.write(f"  [background cleanup] {' '.join(cmd[1:])}: {reclaimed}\n")
            except Exception as e:  # noqa: BLE001
                with log_path.open("a") as log_f:
                    log_f.write(f"  [background cleanup] {' '.join(cmd[1:])} failed: {e}\n")

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=5)


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

    @staticmethod
    def _resolve_instance_selection(
        dataset_name: str,
        split: str,
        instance_id_filter: str | None,
        run_all: bool,
        run_first_n: int | None,
    ) -> tuple[str | None, int, str | None]:
        """Return (target_instance_id, total_instances, slice_spec) for the requested mode."""
        if run_first_n is not None:
            return None, run_first_n, f"0:{run_first_n}"
        if run_all:
            from datasets import load_dataset

            total = len(load_dataset(dataset_name, split=split))  # nosec B615
            return None, total, None
        target_instance_id = instance_id_filter
        if target_instance_id is None:
            from datasets import load_dataset

            dataset = load_dataset(dataset_name, split=split)  # nosec B615
            target_instance_id = sorted(dataset["instance_id"])[0]
        return target_instance_id, 1, None

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
        first_n_match = re.match(r"^__first_(\d+)__$", instance_id_filter or "")
        run_first_n = int(first_n_match.group(1)) if first_n_match else None
        run_batch = run_all or run_first_n is not None

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
            target_instance_id, total_instances, slice_spec = self._resolve_instance_selection(
                dataset_name, split, instance_id_filter, run_all, run_first_n
            )

            (run_dir / "manifest.json").write_text(json.dumps({"total": total_instances}))

            workers = os.environ.get("SWE_BENCH_MAX_WORKERS", "4" if run_batch else "1")
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
            if slice_spec:
                agent_cmd += ["--slice", slice_spec]

            log_path.write_text("running mini-swe-agent to generate patch(es)...\n")
            if run_batch:
                with log_path.open("a") as log_f:
                    log_f.write("  background image cleanup enabled (pruning every 2 min)\n")

            pruner = _background_image_pruner(log_path) if run_batch else nullcontext()
            with pruner:
                with log_path.open("a") as log_f:
                    log_f.flush()
                    agent_proc = subprocess.run(  # noqa: S603 # nosec B603
                        agent_cmd,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        timeout=21600 if run_batch else 1800,
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
                        "--clean",
                        "true",
                    ]
                    if target_instance_id:
                        harness_cmd += ["--instance_ids", target_instance_id]
                    harness_proc = subprocess.run(  # noqa: S603 # nosec B603
                        harness_cmd,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        timeout=21600 if run_batch else 1800,
                        cwd=run_dir,
                        check=False,
                    )

            report_path = next(run_dir.glob(f"*.{run_id}.json"), None)
            if report_path is not None and report_path.exists():
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
