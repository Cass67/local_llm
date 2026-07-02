"""SWE-bench runner: generates a real model patch and evaluates it with the actual harness."""

import json
import os
import subprocess  # noqa: S404 # nosec B404
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .base import BaseBenchmarkRunner

_RUNS_DIR = Path("/tmp/swe_bench_runs")  # noqa: S108 # nosec B108


def _extract_patch(text: str) -> str:
    if "```diff" in text:
        return text.split("```diff", 1)[1].split("```", 1)[0].strip()
    if "```patch" in text:
        return text.split("```patch", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].rsplit("```", 1)[0].strip()
    return text.strip()


class SwebenchRunner(BaseBenchmarkRunner):
    """Generates a model patch for a SWE-bench instance and scores it with the real harness."""

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

    def run(
        self,
        endpoint_id: int,
        model: str,
        prompt_text: str,
        **kwargs,
    ) -> dict[str, Any]:
        endpoint_name = kwargs.get("endpoint_name", "swe-bench")
        endpoint_base_url = kwargs.get("endpoint_base_url", "")
        dataset_name = os.environ.get("SWE_BENCH_DATASET_NAME", "princeton-nlp/SWE-bench_Lite")
        split = os.environ.get("SWE_BENCH_SPLIT", "test")
        instance_id_filter = prompt_text.strip() or None

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
            from datasets import load_dataset

            log_path.write_text("loading dataset...\n")
            dataset = load_dataset(dataset_name, split=split)  # nosec B615
            instance = None
            if instance_id_filter:
                for row in dataset:
                    if row["instance_id"] == instance_id_filter:
                        instance = row
                        break
                if instance is None:
                    raise ValueError(f"instance_id {instance_id_filter!r} not found in dataset")
            else:
                instance = dataset[0]

            instance_id = instance["instance_id"]
            problem_statement = instance["problem_statement"]

            user_prompt = (
                "You are fixing a bug in an open-source repository. Given the issue "
                "description below, produce a fix as a unified diff patch (git diff format). "
                "Only output the patch, wrapped in a ```diff code block.\n\n"
                f"Issue:\n{problem_statement}"
            )

            with log_path.open("a") as log_f:
                log_f.write(f"instance: {instance_id}\nquerying model for a patch...\n")

            with httpx.Client(timeout=600.0) as client:
                headers = {}
                api_key = kwargs.get("api_key")
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = client.post(
                    f"{endpoint_base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": user_prompt}],
                        "max_tokens": kwargs.get("max_tokens", 2048),
                        "temperature": kwargs.get("temperature", 0.2),
                    },
                )
                resp.raise_for_status()
                completion = resp.json()

            message = completion["choices"][0]["message"]["content"]
            patch = _extract_patch(message)
            usage = completion.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")

            predictions_path = run_dir / "predictions.json"
            predictions_path.write_text(
                json.dumps(
                    [
                        {
                            "instance_id": instance_id,
                            "model_name_or_path": model,
                            "model_patch": patch,
                        }
                    ]
                )
            )

            with log_path.open("a") as log_f:
                log_f.write(f"got patch ({len(patch)} chars), running evaluation harness...\n")
                log_f.flush()
                proc = subprocess.run(  # noqa: S603 # nosec B603
                    [
                        sys.executable,
                        "-m",
                        "swebench.harness.run_evaluation",
                        "--predictions_path",
                        str(predictions_path),
                        "--dataset_name",
                        dataset_name,
                        "--split",
                        split,
                        "--instance_ids",
                        instance_id,
                        "--run_id",
                        run_id,
                        "--max_workers",
                        "1",
                        "--report_dir",
                        str(run_dir),
                    ],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    timeout=1800,
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
                error = tail or f"swebench harness produced no report (exit {proc.returncode})"
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
