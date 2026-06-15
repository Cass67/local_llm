import { describe, expect, it } from "vitest";
import { formatMs, formatThroughput, runDelta } from "./benchmarkMetrics";

describe("benchmark metrics", () => {
	it("formats latency and throughput", () => {
		expect(formatMs(123.45)).toBe("123 ms");
		expect(formatThroughput(42.12, null)).toBe("42.1 tok/s");
		expect(formatThroughput(null, 512.8)).toBe("513 chars/s");
		expect(formatThroughput(null, null)).toBe("-");
	});

	it("computes delta versus average", () => {
		expect(runDelta(120, 100)).toBe("+20.0%");
		expect(runDelta(80, 100)).toBe("-20.0%");
		expect(runDelta(null, 100)).toBe("-");
	});
});
