import { describe, expect, it } from "vitest";
import { normalizeMtpConfig, splitMtpFlags } from "./mtpFlags";

describe("splitMtpFlags", () => {
	it("extracts MTP settings and removes them from raw flags", () => {
		const result = splitMtpFlags(
			"--foo bar --spec-type draft-mtp --spec-draft-n-max 3 --spec-draft-n-min 1 --spec-draft-p-min 0.5 --baz",
		);

		expect(result.mtp).toEqual({
			enabled: true,
			draft_n_max: 3,
			draft_n_min: 1,
			draft_p_min: 0.5,
		});
		expect(result.flags).toBe("--foo bar --baz");
	});

	it("returns disabled defaults when no MTP flags exist", () => {
		const result = splitMtpFlags("--foo bar");

		expect(result.mtp).toEqual({
			enabled: false,
			draft_n_max: 3,
			draft_n_min: 1,
			draft_p_min: 0.5,
		});
		expect(result.flags).toBe("--foo bar");
	});

	it("prefers existing structured MTP values over raw flag defaults", () => {
		const normalized = normalizeMtpConfig(
			{ enabled: true, draft_n_max: 5, draft_n_min: 2, draft_p_min: 0.25 },
			"--spec-type draft-mtp --spec-draft-n-max 3",
		);

		expect(normalized.mtp).toEqual({
			enabled: true,
			draft_n_max: 5,
			draft_n_min: 2,
			draft_p_min: 0.25,
		});
		expect(normalized.flags).toBe("");
	});
});
