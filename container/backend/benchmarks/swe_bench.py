"""SWE-bench runner: generates a real model patch and evaluates it with the actual harness."""

import json
import logging
import os
import re
import shutil
import subprocess  # noqa: S404 # nosec B404
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .base import BaseBenchmarkRunner

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("datasets").setLevel(logging.WARNING)

_STATE_DIR = Path(os.environ.get("LOCAL_LLM_STATE_DIR", "/state"))
_RUNS_DIR = _STATE_DIR / "runs" / "benchmarks" / "swe_bench"
_REPOS_DIR = _STATE_DIR / "runs" / "benchmarks" / "swe_bench_repos"
_SKIP_DIR_PARTS = {".git", "tests", "test", "testing", "migrations", "docs", "examples"}
_STOPWORDS = {
    "this",
    "that",
    "with",
    "from",
    "have",
    "when",
    "does",
    "should",
    "would",
    "could",
    "which",
    "there",
    "using",
    "into",
    "your",
    "also",
}


def _git(*args: str, timeout: float) -> None:
    git_bin = shutil.which("git") or "git"
    subprocess.run([git_bin, *args], check=True, timeout=timeout)  # noqa: S603 # nosec B603


def _checkout_repo(repo: str, base_commit: str) -> Path | None:
    """Shallow-clone a repo at a specific commit, cached by (repo, commit)."""
    dest = _REPOS_DIR / f"{repo.replace('/', '__')}_{base_commit}"
    if (dest / ".git").is_dir():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    try:
        _git("init", "-q", str(dest), timeout=60)
        _git("-C", str(dest), "remote", "add", "origin", url, timeout=60)
        _git("-C", str(dest), "fetch", "--depth", "1", "origin", base_commit, timeout=300)
        _git("-C", str(dest), "checkout", "-q", "FETCH_HEAD", timeout=60)
        return dest
    except Exception:  # noqa: BLE001
        return None


def _relevant_files(
    repo_dir: Path, problem_statement: str, top_n: int = 4, max_file_chars: int = 6000
) -> list[tuple[str, str]]:
    """Cheap keyword-overlap search over the repo for files likely relevant to the issue."""
    keywords = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", problem_statement.lower()))
    keywords -= _STOPWORDS
    if not keywords:
        return []

    scored: list[tuple[float, Path, str]] = []
    for path in repo_dir.rglob("*.py"):
        if _SKIP_DIR_PARTS & set(path.relative_to(repo_dir).parts):
            continue
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue
        text = content.lower()
        # normalize by file length so one huge file doesn't win purely on size,
        # then add a strong bonus if a keyword appears in the filename itself
        hits = sum(text.count(kw) for kw in keywords)
        density = hits / max(len(text), 1) * 1000
        stem = path.stem.lower()
        name_bonus = 50 * sum(kw in stem or stem in kw for kw in keywords if len(stem) >= 4)
        score = density + name_bonus
        if hits > 0 or name_bonus > 0:
            scored.append((score, path, content))

    scored.sort(key=lambda item: -item[0])
    return [
        (str(path.relative_to(repo_dir)), content[:max_file_chars])
        for _, path, content in scored[:top_n]
    ]


def _extract_patch(text: str) -> str:
    if "```diff" in text:
        patch = text.split("```diff", 1)[1].split("```", 1)[0].strip()
    elif "```patch" in text:
        patch = text.split("```patch", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        patch = text.split("```", 1)[1].rsplit("```", 1)[0].strip()
    else:
        patch = text.strip()
    # unified diffs must end with a trailing newline or `patch` rejects the last hunk
    return patch + "\n" if patch else patch


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

    def list_tasks(self) -> list[str]:
        from datasets import load_dataset

        dataset_name = os.environ.get("SWE_BENCH_DATASET_NAME", "princeton-nlp/SWE-bench_Lite")
        split = os.environ.get("SWE_BENCH_SPLIT", "test")
        dataset = load_dataset(dataset_name, split=split)  # nosec B615
        return sorted(dataset["instance_id"])

    def _generate_predictions(
        self,
        instances: list[dict[str, Any]],
        model: str,
        endpoint_base_url: str,
        log_path: Path,
        **kwargs,
    ) -> tuple[list[dict[str, str]], int, int]:
        predictions: list[dict[str, str]] = []
        prompt_tokens = 0
        completion_tokens = 0
        max_tokens = kwargs.get("max_tokens", 2048)
        temperature = kwargs.get("temperature", 0.2)
        api_key = kwargs.get("api_key")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        with httpx.Client(timeout=600.0) as client:
            for i, instance in enumerate(instances, start=1):
                instance_id = instance["instance_id"]
                with log_path.open("a") as log_f:
                    log_f.write(
                        f"[{i}/{len(instances)}] instance: {instance_id} — checking out repo...\n"
                    )
                repo_dir = _checkout_repo(instance["repo"], instance["base_commit"])
                context = ""
                if repo_dir is not None:
                    files = _relevant_files(repo_dir, instance["problem_statement"])
                    if files:
                        context = "\n\n".join(
                            f"--- current contents of {path} ---\n{content}"
                            for path, content in files
                        )
                        with log_path.open("a") as log_f:
                            names = ", ".join(p for p, _ in files)
                            log_f.write(f"  found likely-relevant files: {names}\n")
                else:
                    with log_path.open("a") as log_f:
                        log_f.write("  repo checkout failed, falling back to issue text only\n")

                with log_path.open("a") as log_f:
                    log_f.write("  querying model for a patch...\n")
                user_prompt = (
                    "You are fixing a bug in an open-source repository. Given the issue "
                    "description and the current contents of the likely-relevant file(s) "
                    "below, produce a fix as a unified diff patch (git diff format) against "
                    "the file contents shown. Only output the patch, wrapped in a ```diff "
                    "code block.\n\n"
                    f"Issue:\n{instance['problem_statement']}"
                    + (f"\n\n{context}" if context else "")
                )
                try:
                    resp = client.post(
                        f"{endpoint_base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": user_prompt}],
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                        },
                    )
                    resp.raise_for_status()
                    completion = resp.json()
                    message = completion["choices"][0]["message"]["content"]
                    patch = _extract_patch(message)
                    usage = completion.get("usage") or {}
                    prompt_tokens += usage.get("prompt_tokens") or 0
                    completion_tokens += usage.get("completion_tokens") or 0
                    predictions.append(
                        {
                            "instance_id": instance_id,
                            "model_name_or_path": model,
                            "model_patch": patch,
                        }
                    )
                    with log_path.open("a") as log_f:
                        log_f.write(f"  got patch ({len(patch)} chars)\n")
                except Exception as e:  # noqa: BLE001
                    with log_path.open("a") as log_f:
                        log_f.write(f"  ERROR generating patch: {e}\n")

        return predictions, prompt_tokens, completion_tokens

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
            from datasets import load_dataset

            log_path.write_text("loading dataset...\n")
            dataset = load_dataset(dataset_name, split=split)  # nosec B615

            if run_all:
                instances = list(dataset)
            elif instance_id_filter:
                instances = [row for row in dataset if row["instance_id"] == instance_id_filter]
                if not instances:
                    raise ValueError(f"instance_id {instance_id_filter!r} not found in dataset")
            else:
                instances = [dataset[0]]

            predictions, prompt_tokens, completion_tokens = self._generate_predictions(
                instances, model, endpoint_base_url, log_path, **kwargs
            )

            if not predictions:
                raise RuntimeError("no patches were generated for any instance")

            predictions_path = run_dir / "predictions.json"
            predictions_path.write_text(json.dumps(predictions))

            with log_path.open("a") as log_f:
                log_f.write(
                    f"generated {len(predictions)}/{len(instances)} patches, "
                    "running evaluation harness...\n"
                )
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
                    os.environ.get("SWE_BENCH_MAX_WORKERS", "4" if run_all else "1"),
                    "--report_dir",
                    str(run_dir),
                ]
                if not run_all:
                    harness_cmd += ["--instance_ids", predictions[0]["instance_id"]]
                proc = subprocess.run(  # noqa: S603 # nosec B603
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
