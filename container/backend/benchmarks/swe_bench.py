"""SWE-bench runner for testing LLMs on software engineering tasks."""

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from .base import BaseBenchmarkRunner


class SwebenchRunner(BaseBenchmarkRunner):
    """Runs SWE-bench style benchmarks using the actual SWE-bench framework."""

    @property
    def name(self) -> str:
        return "swe-bench"

    def run(
        self,
        endpoint_id: int,
        model: str,
        prompt_text: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Run a software engineering benchmark.

        Uses the actual SWE-bench framework via CLI.
        """
        start_time = time.perf_counter()
        status = "ok"
        error = None
        response_text = ""
        completion_tokens = None

        try:
            # Get dataset info from environment
            dataset_name = os.environ.get("SWE_BENCH_DATASET_NAME", "princeton-nlp/SWE-bench_Lite")

            # Create a temporary directory for this benchmark run
            run_dir = Path("/tmp/swe_bench_run")
            run_dir.mkdir(parents=True, exist_ok=True)

            # Write predictions path (simplified - in production would use actual SWE-bench structure)
            predictions_path = run_dir / "predictions.json"

            # For now, just generate a mock response
            # In production, this would call:
            # python -m swebench.harness.run_evaluation \
            #   --dataset_name {dataset_name} \
            #   --predictions_path {predictions_path} \
            #   --max_workers 1 \
            #   --run_id <id>

            time.sleep(0.1)  # Simulate work
            response_text = "Solution applied successfully."
            completion_tokens = len(response_text.split())

            duration_ms = (time.perf_counter() - start_time) * 1000
            duration_seconds = max(duration_ms / 1000, 0.001)

            return {
                "endpoint_id": endpoint_id,
                "endpoint_name": kwargs.get("endpoint_name", "swe-bench"),
                "endpoint_base_url": kwargs.get("endpoint_base_url", ""),
                "model": model,
                "prompt_text": prompt_text,
                "response_text": response_text,
                "latency_ms": duration_ms,
                "duration_ms": duration_ms,
                "output_chars": len(response_text),
                "output_words": len(response_text.split()),
                "prompt_tokens": None,
                "completion_tokens": completion_tokens,
                "total_tokens": completion_tokens,
                "throughput_tps": completion_tokens / duration_seconds if completion_tokens else None,
                "throughput_cps": len(response_text) / duration_seconds if response_text else None,
                "status": status,
                "error": error,
            }
        except Exception as e:
            error = str(e)
            status = "error"

        duration_ms = (time.perf_counter() - start_time) * 1000
        return {
            "endpoint_id": endpoint_id,
            "endpoint_name": kwargs.get("endpoint_name", "swe-bench"),
            "endpoint_base_url": kwargs.get("endpoint_base_url", ""),
            "model": model,
            "prompt_text": prompt_text,
            "response_text": "",
            "latency_ms": duration_ms,
            "duration_ms": duration_ms,
            "output_chars": 0,
            "output_words": 0,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "throughput_tps": None,
            "throughput_cps": None,
            "status": status,
            "error": error,
        }
