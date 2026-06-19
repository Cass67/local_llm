import { describe, expect, it } from "vitest";
import { splitKnownFlags } from "./mtpFlags";

describe("splitKnownFlags", () => {
	it("strips MTP flags and returns clean flags", () => {
		const result = splitKnownFlags(
			"--foo bar --spec-type draft-mtp --spec-draft-n-max 3 --spec-draft-n-min 1 --spec-draft-p-min 0.5 --baz",
		);
		expect(result.flags).toBe("--foo bar --baz");
		expect(result.flash_attention).toBe(false);
	});

	it("extracts flash attention and jinja", () => {
		const result = splitKnownFlags("-fa on --jinja --extra");
		expect(result.flash_attention).toBe(true);
		expect(result.jinja).toBe(true);
		expect(result.flags).toBe("--extra");
	});

	it("returns clean flags when nothing to strip", () => {
		const result = splitKnownFlags("--foo bar");
		expect(result.flags).toBe("--foo bar");
		expect(result.flash_attention).toBe(false);
		expect(result.jinja).toBe(false);
	});
});
