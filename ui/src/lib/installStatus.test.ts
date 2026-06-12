import { describe, expect, it } from "vitest";
import { installStatusView } from "./installStatus";
import type { InstallErrorDetail } from "./types";

describe("installStatusView", () => {
	it("formats installed status without a detail reason", () => {
		expect(installStatusView("installed")).toEqual({
			label: "✓ Installed",
			reason: "",
		});
	});

	it("formats failure status with a visible reason", () => {
		expect(
			installStatusView("PermissionError: [Errno 13] Permission denied"),
		).toEqual({
			label: "✗ Failed",
			reason: "PermissionError: [Errno 13] Permission denied",
		});
	});

	it("formats structured install errors with phase context", () => {
		const error: InstallErrorDetail = {
			status: "error",
			phase: "download",
			detail: "HTTP 502 Bad Gateway",
		};

		expect(installStatusView(error)).toEqual({
			label: "✗ Failed",
			reason: "download: HTTP 502 Bad Gateway",
		});
	});
});
