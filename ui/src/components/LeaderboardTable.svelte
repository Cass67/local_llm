<script lang="ts">
	import { onMount } from "svelte";
	import { fetchLeaderboard } from "../lib/benchmarkApi";
	import type { LeaderboardRow } from "../lib/benchmarkApi";

	const STALE_DAYS = 14;

	type Col = {
		key: string;
		label: string;
		hint: string;
		value: (row: LeaderboardRow) => number | null;
		format: (row: LeaderboardRow) => string;
		// Higher is better for most columns; latency is the exception.
		lowerIsBetter?: boolean;
	};

	const AGENTIC = [
		{ type: "terminal-bench", label: "Term-bench" },
		{ type: "swe-bench", label: "SWE-bench" },
	];

	const COLS: Col[] = [
		{
			key: "best_tps",
			label: "Best tok/s",
			hint: "fastest standard run recorded for this model+profile",
			value: (r) => r.best_tps,
			format: (r) => (r.best_tps == null ? "—" : r.best_tps.toFixed(1)),
		},
		{
			key: "avg_tps",
			label: "Avg tok/s",
			hint: "mean across every standard run",
			value: (r) => r.avg_tps,
			format: (r) => (r.avg_tps == null ? "—" : r.avg_tps.toFixed(1)),
		},
		{
			key: "avg_latency_ms",
			label: "Avg run",
			hint: "whole-request wall time, not TTFT — varies with max_tokens",
			value: (r) => r.avg_latency_ms,
			format: (r) => (r.avg_latency_ms == null ? "—" : `${(r.avg_latency_ms / 1000).toFixed(1)} s`),
			lowerIsBetter: true,
		},
		{
			key: "best_tps_per_watt",
			label: "tok/s/W",
			hint: "throughput per watt of wall draw (PSU, not GPU sensors)",
			value: (r) => r.best_tps_per_watt,
			format: (r) => (r.best_tps_per_watt == null ? "—" : r.best_tps_per_watt.toFixed(3)),
		},
		{
			key: "avg_psu_w",
			label: "Avg W",
			hint: "mean wall draw during runs",
			value: (r) => r.avg_psu_w,
			format: (r) => (r.avg_psu_w == null ? "—" : r.avg_psu_w.toFixed(0)),
			lowerIsBetter: true,
		},
		{
			key: "quality_pass_rate",
			label: "Quality",
			hint: "latest golden-set pass rate, judge score in brackets",
			value: (r) => r.quality_pass_rate,
			format: (r) =>
				r.quality_pass_rate == null
					? "—"
					: `${(r.quality_pass_rate * 100).toFixed(0)}%` +
						(r.quality_judge_mean == null ? "" : ` (${r.quality_judge_mean.toFixed(1)})`),
		},
		...AGENTIC.map(({ type, label }) => ({
			key: type,
			label,
			hint: `latest ${type} score`,
			value: (r: LeaderboardRow) => r.agentic[type]?.rate ?? null,
			format: (r: LeaderboardRow) => {
				const score = r.agentic[type];
				return score ? `${score.resolved}/${score.total}` : "—";
			},
		})),
	];

	let rows = $state<LeaderboardRow[]>([]);
	let error = $state("");
	let loading = $state(true);
	let sortKey = $state("best_tps");
	let sortAsc = $state(false);

	export async function load() {
		loading = true;
		try {
			rows = (await fetchLeaderboard()).rows;
			error = "";
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function sortBy(key: string) {
		if (sortKey === key) sortAsc = !sortAsc;
		else {
			sortKey = key;
			sortAsc = COLS.find((c) => c.key === key)?.lowerIsBetter ?? false;
		}
	}

	const sorted = $derived.by(() => {
		const col = COLS.find((c) => c.key === sortKey);
		if (!col) return rows;
		// Rows with no measurement for the sorted column always sink to the bottom.
		return [...rows].sort((a, b) => {
			const av = col.value(a);
			const bv = col.value(b);
			if (av == null && bv == null) return 0;
			if (av == null) return 1;
			if (bv == null) return -1;
			return sortAsc ? av - bv : bv - av;
		});
	});

	const leaders = $derived.by(() => {
		const best: Record<string, number> = {};
		for (const col of COLS) {
			const values = rows.map(col.value).filter((v): v is number => v != null);
			if (values.length > 1) {
				best[col.key] = col.lowerIsBetter ? Math.min(...values) : Math.max(...values);
			}
		}
		return best;
	});

	function isStale(at: string | null): boolean {
		if (!at) return true;
		const age = Date.now() - new Date(`${at}Z`).getTime();
		return age > STALE_DAYS * 86400_000;
	}

	function ago(at: string | null): string {
		if (!at) return "never";
		const days = Math.floor((Date.now() - new Date(`${at}Z`).getTime()) / 86400_000);
		if (days < 1) return "today";
		return days === 1 ? "1 day ago" : `${days} days ago`;
	}

	onMount(load);
</script>

<section class="panel">
	<div class="head">
		<div>
			<h3>Leaderboard</h3>
			<p class="muted">
				One row per model and profile — speed, power, golden-set quality and agentic scores from
				every standard run recorded. Bold is the best in that column.
			</p>
		</div>
		<button onclick={load} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>
	</div>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if !loading && rows.length === 0}
		<p class="muted">No runs recorded yet. Run a benchmark and it shows up here.</p>
	{:else}
		<div class="scroll">
			<table>
				<thead>
					<tr>
						<th>Model</th>
						<th>Profile</th>
						<th class="num">Runs</th>
						{#each COLS as col}
							<th
								class="num sortable"
								class:sorted={sortKey === col.key}
								title={col.hint}
								onclick={() => sortBy(col.key)}
							>
								{col.label}{sortKey === col.key ? (sortAsc ? " ↑" : " ↓") : ""}
							</th>
						{/each}
						<th>Last run</th>
					</tr>
				</thead>
				<tbody>
					{#each sorted as row (row.model + (row.profile ?? ""))}
						<tr class:stale={isStale(row.last_run)}>
							<td class="model">{row.model}</td>
							<td class="muted-cell">{row.profile ?? "—"}</td>
							<td class="num muted-cell">{row.runs}</td>
							{#each COLS as col}
								<td class="num" class:leader={col.value(row) != null && col.value(row) === leaders[col.key]}>
									{col.format(row)}
								</td>
							{/each}
							<td class="muted-cell" title={row.last_run ?? ""}>{ago(row.last_run)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="muted footnote">
			Greyed rows have not been measured in {STALE_DAYS} days — treat their numbers as history, not
			as the current build.
		</p>
	{/if}
</section>

<style>
	.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; }
	.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
	h3 { margin: 0 0 0.3rem; }
	.muted { color: var(--text-muted); margin: 0; }
	button { cursor: pointer; background: var(--accent); color: white; border: 1px solid var(--border); border-radius: 8px; padding: 0.55rem; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.error { background: var(--red); color: white; padding: 0.75rem; border-radius: 8px; margin: 0.5rem 0; }
	.scroll { overflow-x: auto; margin-top: 0.75rem; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	th, td { padding: 0.6rem 0.4rem; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
	th { color: var(--text-muted); font-weight: normal; }
	th.sortable { cursor: pointer; user-select: none; }
	th.sorted { color: var(--text); }
	.num { text-align: right; }
	.model { overflow-wrap: anywhere; white-space: normal; }
	.muted-cell { color: var(--text-muted); }
	.leader { font-weight: bold; color: var(--accent); }
	tr.stale td { opacity: 0.45; }
	.footnote { font-size: 0.78rem; margin-top: 0.75rem; }
</style>
