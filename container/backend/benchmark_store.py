"""SQLite persistence for benchmark dashboard."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

# terminal-bench and swe-bench record their score in the response text as
# "3/10 tasks resolved" — there is no numeric column for it.
RESOLVED_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def _empty_leaderboard_row(model: str, profile: str | None) -> dict[str, Any]:
    return {
        "model": model,
        "profile": profile or None,
        "runs": 0,
        "best_tps": None,
        "avg_tps": None,
        "avg_latency_ms": None,
        "best_tps_per_watt": None,
        "avg_psu_w": None,
        "quality_pass_rate": None,  # nosec B105 -- a pass rate, not a password
        "quality_judge_mean": None,
        "quality_at": None,
        "agentic": {},
        "last_run": None,
    }


def _note_last(row: dict[str, Any], at: str | None) -> None:
    if at and (row["last_run"] is None or at > row["last_run"]):
        row["last_run"] = at


def _agentic_score(response_text: str | None, created_at: str) -> dict[str, Any] | None:
    match = RESOLVED_RE.search(response_text or "")
    if not match:
        return None
    resolved, total = int(match.group(1)), int(match.group(2))
    if total <= 0:
        return None
    return {
        "resolved": resolved,
        "total": total,
        "rate": round(resolved / total, 3),
        "at": created_at,
    }


class BenchmarkStore:
    """Persist benchmark endpoints, prompt presets, and runs in SQLite."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists endpoints (
                    id integer primary key autoincrement,
                    name text not null,
                    base_url text not null,
                    api_key text,
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp
                );
                create table if not exists prompt_presets (
                    id integer primary key autoincrement,
                    name text not null,
                    text text not null,
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp
                );
                create table if not exists benchmark_runs (
                    id integer primary key autoincrement,
                    endpoint_id integer,
                    endpoint_name text not null,
                    endpoint_base_url text not null,
                    model text not null,
                    prompt_id integer,
                    prompt_name text,
                    prompt_text text not null,
                    response_text text not null,
                    latency_ms real,
                    duration_ms real,
                    output_chars integer not null,
                    output_words integer not null,
                    prompt_tokens integer,
                    completion_tokens integer,
                    total_tokens integer,
                    throughput_tps real,
                    throughput_cps real,
                    status text not null,
                    error text,
                    benchmark_type text not null default 'standard',
                    created_at text not null default current_timestamp
                );
                create table if not exists quality_runs (
                    id integer primary key autoincrement,
                    model text not null,
                    profile text,
                    cluster_id text,
                    passed integer not null,
                    total integer not null,
                    pass_rate real not null,
                    judge_mean real,
                    created_at text not null default current_timestamp
                );
                """
            )
            columns = {row[1] for row in conn.execute("pragma table_info(benchmark_runs)")}
            if "benchmark_type" not in columns:
                conn.execute(
                    "alter table benchmark_runs add column benchmark_type text not null"
                    " default 'standard'"
                )
            if "run_id" not in columns:
                conn.execute("alter table benchmark_runs add column run_id text")
            # Wall power during the run, so throughput can be read per watt.
            for column, coltype in (
                ("psu_avg_w", "real"),
                ("psu_peak_w", "real"),
                ("gpu_avg_w", "real"),
                ("tps_per_watt", "real"),
                ("profile", "text"),
            ):
                if column not in columns:
                    conn.execute(
                        f"alter table benchmark_runs add column {column} {coltype}"  # noqa: S608 # nosec B608 -- names from code
                    )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _endpoint_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "base_url": row["base_url"],
            "api_key_set": bool(row["api_key"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_endpoint(self, name: str, base_url: str, api_key: str | None) -> dict[str, Any]:
        clean_key = api_key if api_key else None
        with self._connect() as conn:
            cur = conn.execute(
                "insert into endpoints (name, base_url, api_key) values (?, ?, ?)",
                (name, base_url.rstrip("/"), clean_key),
            )
            row = conn.execute("select * from endpoints where id = ?", (cur.lastrowid,)).fetchone()
        return self._endpoint_row(row)

    def upsert_endpoint(self, name: str, base_url: str) -> dict[str, Any]:
        clean_url = base_url.rstrip("/").replace("localhost", "127.0.0.1")
        with self._connect() as conn:
            row = conn.execute(
                "select * from endpoints where name = ?",
                (name,),
            ).fetchone()
            if row:
                conn.execute(
                    "update endpoints set base_url = ?, updated_at = current_timestamp"
                    " where id = ?",
                    (clean_url, row["id"]),
                )
                row = conn.execute("select * from endpoints where id = ?", (row["id"],)).fetchone()
            else:
                cur = conn.execute(
                    "insert into endpoints (name, base_url) values (?, ?)",
                    (name, clean_url),
                )
                row = conn.execute(
                    "select * from endpoints where id = ?", (cur.lastrowid,)
                ).fetchone()
        return self._endpoint_row(row)

    def list_endpoints(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from endpoints order by name").fetchall()
        return [self._endpoint_row(row) for row in rows]

    def get_endpoint_secret(self, endpoint_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("select * from endpoints where id = ?", (endpoint_id,)).fetchone()
        return dict(row) if row else None

    def delete_endpoint(self, endpoint_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("delete from endpoints where id = ?", (endpoint_id,))
        return cur.rowcount > 0

    def create_prompt(self, name: str, text: str) -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                "insert into prompt_presets (name, text) values (?, ?)",
                (name, text),
            )
            row = conn.execute(
                "select * from prompt_presets where id = ?", (cur.lastrowid,)
            ).fetchone()
        return self._row(row)

    def list_prompts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from prompt_presets order by name").fetchall()
        return [self._row(row) for row in rows]

    def delete_prompt(self, prompt_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("delete from prompt_presets where id = ?", (prompt_id,))
        return cur.rowcount > 0

    def create_run(self, benchmark_type: str = "standard", **values: Any) -> dict[str, Any]:
        values["benchmark_type"] = benchmark_type
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        with self._connect() as conn:
            cur = conn.execute(
                f"insert into benchmark_runs ({columns}) values ({placeholders})",  # noqa: S608 # nosec B608 -- columns from code
                tuple(values.values()),
            )
            row = conn.execute(
                "select * from benchmark_runs where id = ?", (cur.lastrowid,)
            ).fetchone()
        return self._row(row)

    def list_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        for key, column in (
            ("endpoint_id", "endpoint_id"),
            ("model", "model"),
            ("prompt_id", "prompt_id"),
            ("status", "status"),
            ("benchmark_type", "benchmark_type"),
            ("profile", "profile"),
        ):
            value = filters.get(key)
            if value not in (None, ""):
                clauses.append(f"{column} = ?")
                params.append(value)
        if filters.get("from_date"):
            clauses.append("created_at >= ?")
            params.append(filters["from_date"])
        if filters.get("to_date"):
            clauses.append("created_at <= ?")
            params.append(filters["to_date"])
        where = f"where {' and '.join(clauses)}" if clauses else ""
        limit = min(int(filters.get("limit", 100)), 500)
        offset = max(int(filters.get("offset", 0)), 0)
        with self._connect() as conn:
            total = conn.execute(f"select count(*) from benchmark_runs {where}", params).fetchone()[  # noqa: S608 # nosec B608
                0
            ]
            rows = conn.execute(
                f"select * from benchmark_runs {where} order by created_at desc limit ? offset ?",  # noqa: S608 # nosec B608
                [*params, limit, offset],
            ).fetchall()
        return {"total": total, "runs": [self._row(row) for row in rows]}

    def create_quality_run(self, **values: Any) -> dict[str, Any]:
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        with self._connect() as conn:
            cur = conn.execute(
                f"insert into quality_runs ({columns}) values ({placeholders})",  # noqa: S608 # nosec B608 -- columns from code
                tuple(values.values()),
            )
            row = conn.execute(
                "select * from quality_runs where id = ?", (cur.lastrowid,)
            ).fetchone()
        return self._row(row)

    def leaderboard(self) -> dict[str, Any]:
        """One row per model+profile, joining speed, power, quality and agentic scores.

        Speed columns aggregate every standard run; quality and agentic scores are
        the latest one of each kind, since they are pass/fail snapshots rather than
        samples worth averaging.
        """
        rows: dict[tuple[str, str], dict[str, Any]] = {}

        def entry(model: str, profile: str | None) -> dict[str, Any]:
            return rows.setdefault((model, profile or ""), _empty_leaderboard_row(model, profile))

        with self._connect() as conn:
            speed = conn.execute(
                """
                select model, profile,
                       count(*) as runs,
                       max(throughput_tps) as best_tps,
                       avg(throughput_tps) as avg_tps,
                       avg(latency_ms) as avg_latency_ms,
                       max(tps_per_watt) as best_tps_per_watt,
                       avg(psu_avg_w) as avg_psu_w,
                       max(created_at) as last_run
                from benchmark_runs
                where status = 'ok' and benchmark_type = 'standard'
                group by model, profile
                """
            ).fetchall()
            agentic = conn.execute(
                """
                select model, profile, benchmark_type, response_text, created_at
                from benchmark_runs
                where status = 'ok' and benchmark_type != 'standard'
                order by created_at asc
                """
            ).fetchall()
            quality = conn.execute("select * from quality_runs order by created_at asc").fetchall()

        for row in speed:
            target = entry(row["model"], row["profile"])
            for key in (
                "runs",
                "best_tps",
                "avg_tps",
                "avg_latency_ms",
                "best_tps_per_watt",
                "avg_psu_w",
            ):
                target[key] = row[key]
            _note_last(target, row["last_run"])

        for row in agentic:
            score = _agentic_score(row["response_text"], row["created_at"])
            if score is None:
                continue
            target = entry(row["model"], row["profile"])
            target["agentic"][row["benchmark_type"]] = score
            _note_last(target, row["created_at"])

        for row in quality:
            target = entry(row["model"], row["profile"])
            target["quality_pass_rate"] = row["pass_rate"]
            target["quality_judge_mean"] = row["judge_mean"]
            target["quality_at"] = row["created_at"]
            _note_last(target, row["created_at"])

        ordered = sorted(
            rows.values(),
            key=lambda r: (r["best_tps"] is None, -(r["best_tps"] or 0)),
        )
        return {"rows": ordered}

    def summary(self, benchmark_type: str | None = None) -> dict[str, Any]:
        conditions = []
        params = []
        if benchmark_type:
            conditions.append("benchmark_type = ?")
            params.append(benchmark_type)

        where = f"where {' and '.join(conditions)}" if conditions else ""

        summary_sql = f"""
            select
              count(*) as total_runs,
              avg(latency_ms) as avg_latency_ms,
              max(throughput_tps) as best_throughput_tps,
              avg(throughput_tps) as avg_throughput_tps,
              sum(case when status != 'ok' then 1 else 0 end) as error_runs
            from benchmark_runs
            {where}
            """  # noqa: S608 # nosec B608
        extra = f"and {' and '.join(conditions)}" if conditions else ""
        best_sql = f"""
            select * from benchmark_runs
            where status = 'ok'
            {extra}
            order by throughput_tps desc nulls last, throughput_cps desc nulls last
            limit 1
            """  # noqa: S608 # nosec B608
        worst_sql = f"""
            select * from benchmark_runs
            where status = 'ok'
            {extra}
            order by latency_ms desc nulls last
            limit 1
            """  # noqa: S608 # nosec B608
        trends_sql = f"""
            select id, created_at, endpoint_name, model, prompt_name, latency_ms,
                   throughput_tps, throughput_cps, status
            from benchmark_runs
            {where}
            order by created_at asc
            limit 200
            """  # noqa: S608 # nosec B608
        with self._connect() as conn:
            row = conn.execute(summary_sql, params).fetchone()
            best = conn.execute(best_sql, params).fetchone()
            worst = conn.execute(worst_sql, params).fetchone()
            trends = conn.execute(trends_sql, params).fetchall()
        total = row["total_runs"] or 0
        errors = row["error_runs"] or 0
        return {
            "total_runs": total,
            "avg_latency_ms": row["avg_latency_ms"],
            "best_throughput_tps": row["best_throughput_tps"],
            "avg_throughput_tps": row["avg_throughput_tps"],
            "error_rate": (errors / total) if total else 0,
            "best_run": self._row(best) if best else None,
            "worst_run": self._row(worst) if worst else None,
            "trends": [self._row(item) for item in trends],
        }
