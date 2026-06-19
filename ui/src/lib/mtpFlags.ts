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
		} else if (
			tok === "--spec-type" ||
			tok === "--spec-draft-n-max" ||
			tok === "--spec-draft-n-min" ||
			tok === "--spec-draft-p-min"
		) {
			i++; // skip value too
		} else {
			kept.push(tok);
		}
	}
	return { flags: kept.join(" "), flash_attention, jinja };
}
