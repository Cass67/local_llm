"""Runtime stats endpoint."""

import json
import sqlite3
import time
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Query

from .. import config

router = APIRouter(prefix="/api", tags=["stats"])

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
