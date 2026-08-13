"""Runtime stats endpoint."""

import asyncio
import json
import logging
import sqlite3
import time
from functools import lru_cache
from typing import Any

import httpx
from fastapi import APIRouter, Query, Response

from .. import active_runners, config, prom_export
from ..gpu_inventory import detect_gpus
from ..gpu_status import GpuStatusCollector, collect_amd_gpu_metrics
from ..system_status import SystemStatusCollector

router = APIRouter(prefix="/api", tags=["stats"])
logger = logging.getLogger(__name__)

_DB_NAME = "chat_metrics.sqlite3"


@lru_cache(maxsize=1)
def _db_path():
    return config.RUNS_DIR / _DB_NAME


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            create table if not exists chat_metrics (
                id integer primary key autoincrement,
                ts real not null,
                model text,
                predicted_per_second real,
                prompt_per_second real,
                draft_n integer,
                draft_n_accepted integer
            )
            """
        )
        conn.execute("create index if not exists chat_metrics_ts on chat_metrics (ts)")


def append_chat_metric(metrics: dict[str, Any]) -> None:
    try:
        _init_db()
        with _connect() as conn:
            conn.execute(
                """
                insert into chat_metrics
                    (ts, model, predicted_per_second, prompt_per_second, draft_n, draft_n_accepted)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    metrics.get("model"),
                    metrics.get("predicted_per_second"),
                    metrics.get("prompt_per_second"),
                    metrics.get("draft_n"),
                    metrics.get("draft_n_accepted"),
                ),
            )
    except (OSError, sqlite3.Error):
        pass


@router.get("/stats")
async def stats():
    path = config.RUNS_DIR / "latest-metrics.json"
    if not path.exists() or path.is_symlink():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/stats/history")
async def stats_history(limit: int = Query(default=50, ge=1, le=500)):
    try:
        _init_db()
        with _connect() as conn:
            rows = conn.execute(
                "select * from chat_metrics order by ts desc limit ?", (limit,)
            ).fetchall()
        return {"metrics": [dict(row) for row in rows]}
    except (OSError, sqlite3.Error):
        return {"metrics": []}


# --- GPU status (fdinfo engine occupancy) ---

_gpu_collector = GpuStatusCollector(docker_socket_path=str(config.DOCKER_SOCKET))
_system_collector = SystemStatusCollector()
_last_gpu_sample: dict | None = None
_gpu_lock = asyncio.Lock()


_VENDOR_LABELS = {"amd": "AMD", "nvidia": "NVIDIA", "intel": "Intel"}


@lru_cache(maxsize=1)
def _gpu_identity() -> dict[str, dict[str, str]]:
    """PCI id → vendor/model labels. Cached: detect_gpus shells out and hardware is fixed."""
    return {
        g.pci_id: {
            "vendor": _VENDOR_LABELS.get(g.vendor, g.vendor.upper()),
            "model_name": g.model_name,
            "board": g.board,
        }
        for g in detect_gpus()
    }


def _get_running_runners():
    """Build list of running runners for sampling."""
    runners = []
    from ..clusters import list_clusters

    clusters = list_clusters()
    for cluster in clusters:
        if active_runners.is_running(cluster):
            from ..clusters import read_active

            active = read_active(cluster.id)
            if not active:
                continue
            container = str(active.get("container") or "")
            if not container:
                continue
            runners.append(
                {
                    "cluster_id": cluster.id,
                    "cluster_name": cluster.name,
                    "container": container,
                    "port": cluster.port,
                    "gpu_pci_ids": list(cluster.gpu_pci_ids),
                }
            )
    return runners


_METRIC_KEYS = (
    "llamacpp:tokens_predicted_total",
    "llamacpp:tokens_predicted_seconds_total",
    "llamacpp:prompt_tokens_total",
    "llamacpp:prompt_seconds_total",
    "llamacpp:requests_processing",
)
# Previous /metrics counter read per runner, for rate deltas.
_metrics_prev: dict[str, dict[str, float]] = {}


def _parse_prom(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        name, _, raw = line.partition(" ")
        if name in _METRIC_KEYS:
            try:
                values[name] = float(raw)
            except ValueError:
                continue
    return values


async def _runner_throughput(runners: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Live tok/s per runner from llama-server's /metrics counters.

    Rates come from token counters divided by the server's own generation-seconds
    counters, not by wall time, so idle gaps between requests do not drag the
    number down. Runners launched before --metrics existed answer 501; they get
    no entry rather than a zero, which would read as "stalled".
    """
    out: dict[str, dict[str, Any]] = {}

    async def sample(runner: dict[str, Any]) -> None:
        container = str(runner.get("container") or "")
        port = runner.get("port")
        if not container or not port:
            return
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"http://127.0.0.1:{port}/metrics")
            if resp.status_code != 200:
                return
            now = _parse_prom(resp.text)
        except (httpx.HTTPError, OSError):
            return
        if not now:
            return
        prev = _metrics_prev.get(container)
        _metrics_prev[container] = now
        entry: dict[str, Any] = {
            "processing": int(now.get("llamacpp:requests_processing", 0)),
        }
        if prev:
            for label, tokens_key, seconds_key in (
                (
                    "tg_tok_s",
                    "llamacpp:tokens_predicted_total",
                    "llamacpp:tokens_predicted_seconds_total",
                ),
                ("pp_tok_s", "llamacpp:prompt_tokens_total", "llamacpp:prompt_seconds_total"),
            ):
                d_tokens = now.get(tokens_key, 0) - prev.get(tokens_key, 0)
                d_seconds = now.get(seconds_key, 0) - prev.get(seconds_key, 0)
                # A restarted runner resets the counters; a negative delta means
                # this sample has no baseline, not a negative rate.
                if d_tokens > 0 and d_seconds > 0:
                    entry[label] = round(d_tokens / d_seconds, 1)
        out[container] = entry

    await asyncio.gather(*(sample(r) for r in runners))
    return out


async def _sample_gpu_status(initial_warmup: bool = False):
    global _last_gpu_sample
    async with _gpu_lock:
        try:
            runners = await asyncio.to_thread(_get_running_runners)
            samples = await asyncio.to_thread(
                lambda: _gpu_collector.sample_all(runners, initial_warmup=initial_warmup)
            )
            devices = await asyncio.to_thread(collect_amd_gpu_metrics)
            identity = await asyncio.to_thread(_gpu_identity)
            for pci_id, dev in devices.items():
                dev.update(identity.get(pci_id, {}))
            for sample in samples:
                for pci_id, gpu in sample.get("gpus", {}).items():
                    gpu.update(identity.get(pci_id, {}))
            throughput = await _runner_throughput(runners)
            for sample in samples:
                sample.update(throughput.get(sample.get("container", ""), {}))
            system = await asyncio.to_thread(_system_collector.sample)
            _last_gpu_sample = {
                "ts": time.time(),
                "runners": samples,
                "devices": sorted(devices.values(), key=lambda d: d["pci_id"]),
                "system": system,
            }
        except Exception as exc:  # noqa: BLE001 - a bad sample must never kill the loop
            logger.warning("gpu-status sample failed: %s", exc, exc_info=True)
            _last_gpu_sample = {
                "ts": time.time(),
                "error": str(exc),
                "runners": [],
                "devices": [],
                "system": {},
            }


@router.get("/metrics")
async def prometheus_metrics():
    """GPU/system telemetry in Prometheus exposition format, for the Grafana stack."""
    if _last_gpu_sample is None:
        await _sample_gpu_status()
    return Response(content=prom_export.render(_last_gpu_sample), media_type="text/plain")


@router.get("/gpu-status")
async def gpu_status():
    """Latest GPU sample: per-runner fdinfo occupancy, per-card sysfs, host system."""
    if _last_gpu_sample is None:
        await _sample_gpu_status()
    return _last_gpu_sample or {"ts": time.time(), "runners": [], "devices": [], "system": {}}


# Background sampling loop — populates data every 2s so UI polls are cheap.


async def _gpu_sampling_loop():
    initial = True
    while True:
        try:
            await _sample_gpu_status(initial_warmup=initial)
            initial = False
        except Exception:  # noqa: BLE001 - loop must survive anything a sample throws
            logger.warning("gpu sampling loop iteration failed", exc_info=True)
        await asyncio.sleep(2)


def start_gpu_sampling():
    """Start the background GPU status sampling loop. Call from main.py startup."""
    asyncio.create_task(_gpu_sampling_loop())
