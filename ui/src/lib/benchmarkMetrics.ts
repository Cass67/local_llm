export function formatMs(value: number | null | undefined): string {
	if (value == null || Number.isNaN(value)) return "-";
	return `${Math.round(value).toLocaleString()} ms`;
}

export function formatThroughput(
	tokensPerSecond: number | null | undefined,
	charsPerSecond: number | null | undefined,
): string {
	if (tokensPerSecond != null && !Number.isNaN(tokensPerSecond)) {
		return `${tokensPerSecond.toFixed(1)} tok/s`;
	}
	if (charsPerSecond != null && !Number.isNaN(charsPerSecond)) {
		return `${Math.round(charsPerSecond).toLocaleString()} chars/s`;
	}
	return "-";
}

export function runDelta(
	current: number | null | undefined,
	baseline: number | null | undefined,
): string {
	if (current == null || baseline == null || baseline === 0) return "-";
	const delta = ((current - baseline) / baseline) * 100;
	const sign = delta > 0 ? "+" : "";
	return `${sign}${delta.toFixed(1)}%`;
}
