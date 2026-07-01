"""Terminal benchmark runner for testing LLMs on command-line tasks."""

import httpx
import time
from typing import Any, Dict

from .base import BaseBenchmarkRunner


class TerminalBenchRunner(BaseBenchmarkRunner):
    """Runs terminal-based benchmarks."""

    worker_port = 3101  # Default port for the containerized worker

    @property
    def name(self) -> str:
        return "terminal-bench"

    def run(
        self,
        endpoint_id: int,
        model: str,
        prompt_text: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Execute a benchmark where the LLM must provide correct terminal commands.

        The prompt should be a task like: "List all files in /tmp"
        We delegate to a containerized worker for security and isolation.
        """
        start_time = time.perf_counter()
        worker_url = f"http://localhost:{kwargs.get('worker_port', self.worker_port)}"

        try:
            # Delegate to containerized worker service
            response = httpx.post(
                f"{worker_url}/run",
                json={
                    "prompt_text": prompt_text,
                    "model": model,
                    "endpoint_id": endpoint_id,
                    "endpoint_name": kwargs.get("endpoint_name", "terminal-bench"),
                    "endpoint_base_url": kwargs.get("endpoint_base_url", ""),
                },
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            error = "Worker request timed out"
            status = "error"
        except Exception as e:
            error = str(e)
            status = "error"

        duration_ms = (time.perf_counter() - start_time) * 1000
        return {
            "endpoint_id": endpoint_id,
            "endpoint_name": kwargs.get("endpoint_name", "terminal-bench"),
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
