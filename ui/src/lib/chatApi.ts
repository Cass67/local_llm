export interface ChatMessage {
	role: "system" | "user" | "assistant";
	content: string;
}

export async function* streamChat(
	model: string,
	messages: ChatMessage[],
	signal?: AbortSignal,
): AsyncGenerator<string> {
	const res = await fetch("/api/local-llm/chat/completions", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			model,
			messages,
			stream: true,
			temperature: 0.7,
			max_tokens: 4096,
		}),
		signal,
	});

	if (!res.ok) {
		const err = await res.text();
		throw new Error(`API error ${res.status}: ${err}`);
	}

	const reader = res.body?.getReader();
	if (!reader) throw new Error("No response body");

	const decoder = new TextDecoder();
	let buffer = "";

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;

		buffer += decoder.decode(value, { stream: true });
		const lines = buffer.split("\n");
		buffer = lines.pop() || "";

		for (const line of lines) {
			const trimmed = line.trim();
			if (!trimmed || !trimmed.startsWith("data: ")) continue;
			const data = trimmed.slice(6);
			if (data === "[DONE]") return;

			try {
				const parsed = JSON.parse(data);
				const content = parsed.choices?.[0]?.delta?.content;
				if (content) yield content;
			} catch {
				// Skip malformed JSON
			}
		}
	}
}
