import type { InstallErrorDetail } from "./types";

export type InstallStatus = "installed" | string | InstallErrorDetail;

export function installStatusView(status: InstallStatus): {
	label: string;
	reason: string;
} {
	if (status === "installed") return { label: "✓ Installed", reason: "" };
	if (typeof status === "string") return { label: "✗ Failed", reason: status };
	const prefix = status.phase ? `${status.phase}: ` : "";
	return { label: "✗ Failed", reason: `${prefix}${status.detail}` };
}
