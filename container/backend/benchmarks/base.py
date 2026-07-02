"""Base class for benchmark runners."""

from abc import ABC, abstractmethod
from typing import Any, Protocol


class BenchmarkResult(Protocol):
    """Protocol for benchmark results."""

    endpoint_id: int | None
    endpoint_name: str
    model: str
    prompt_text: str
    response_text: str
    latency_ms: float
    status: str
    error: str | None
    extra_data: dict[str, Any]


class BaseBenchmarkRunner(ABC):
    """Base class for benchmark runners."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the benchmark name (e.g., 'terminal-bench', 'swe-bench')."""
        pass

    @abstractmethod
    def run(
        self,
        endpoint_id: int,
        model: str,
        prompt_text: str,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Run the benchmark. Returns a dict with keys matching BenchmarkRun schema.

        Args:
            endpoint_id: The endpoint ID to use for the benchmark.
            model: The model name to use.
            prompt_text: The text prompt for the benchmark.
            **kwargs: Additional arguments (e.g., worker_port, system_prompt).

        Returns:
            A dict with benchmark results.

        Must include:
        - endpoint_id, endpoint_name, model, prompt_text, response_text
        - latency_ms, status, error
        - output_chars, output_words, prompt_tokens, completion_tokens, total_tokens
        - throughput_tps, throughput_cps
        """
        pass

    def validate(self, req: dict[str, Any]) -> list[str]:
        """Validate the request. Returns list of error messages."""
        errors = []
        if not req.get("endpoint_id"):
            errors.append("endpoint_id is required")
        if not req.get("model"):
            errors.append("model is required")
        if not req.get("prompt_text"):
            errors.append("prompt_text is required")
        return errors

    def list_tasks(self) -> list[str]:
        """Return the selectable task/instance IDs for this benchmark's dataset."""
        return []
