export interface MtpConfig {
	enabled: boolean;
	draft_n_max: number;
	draft_n_min: number;
	draft_p_min: number;
}

const DEFAULT_MTP: MtpConfig = {
	enabled: false,
	draft_n_max: 3,
	draft_n_min: 1,
	draft_p_min: 0.5,
};

export function splitMtpFlags(flags: string | undefined): {
	flags: string;
	mtp: MtpConfig;
} {
	const tokens = (flags || "").trim().split(/\s+/).filter(Boolean);
	const kept: string[] = [];
	const mtp = { ...DEFAULT_MTP };

	for (let i = 0; i < tokens.length; i += 1) {
		const token = tokens[i];
		if (token === "--spec-type" && tokens[i + 1] === "draft-mtp") {
			mtp.enabled = true;
			i += 1;
			continue;
		}
		if (token === "--spec-draft-n-max" && tokens[i + 1]) {
			mtp.enabled = true;
			mtp.draft_n_max = Number(tokens[i + 1]);
			i += 1;
			continue;
		}
		if (token === "--spec-draft-n-min" && tokens[i + 1]) {
			mtp.enabled = true;
			mtp.draft_n_min = Number(tokens[i + 1]);
			i += 1;
			continue;
		}
		if (token === "--spec-draft-p-min" && tokens[i + 1]) {
			mtp.enabled = true;
			mtp.draft_p_min = Number(tokens[i + 1]);
			i += 1;
			continue;
		}
		kept.push(token);
	}

	return { flags: kept.join(" "), mtp };
}

export function splitKnownFlags(flags: string | undefined): {
	flags: string;
	flash_attention: boolean;
	jinja: boolean;
} {
	const tokens = (flags || "").trim().split(/\s+/).filter(Boolean);
	const kept: string[] = [];
	let flash_attention = false;
	let jinja = false;
	for (let i = 0; i < tokens.length; i++) {
		const tok = tokens[i];
		if (tok === "-fa" || tok === "--flash-attn") {
			const next = tokens[i + 1];
			if (next === "on" || next === "off") { flash_attention = next === "on"; i++; }
			else { flash_attention = true; }
		} else if (tok === "--jinja") {
			jinja = true;
		} else {
			kept.push(tok);
		}
	}
	return { flags: kept.join(" "), flash_attention, jinja };
}

export function normalizeMtpConfig(
	mtp: Partial<MtpConfig> | undefined,
	flags: string | undefined,
): { flags: string; mtp: MtpConfig } {
	const parsed = splitMtpFlags(flags);
	return {
		flags: parsed.flags,
		mtp: {
			enabled: mtp?.enabled ?? parsed.mtp.enabled,
			draft_n_max: mtp?.draft_n_max ?? parsed.mtp.draft_n_max,
			draft_n_min: mtp?.draft_n_min ?? parsed.mtp.draft_n_min,
			draft_p_min: mtp?.draft_p_min ?? parsed.mtp.draft_p_min,
		},
	};
}
