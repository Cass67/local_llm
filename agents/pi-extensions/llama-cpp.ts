import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type LlamaCppModel = {
  id: string;
  name?: string;
  context_window?: number;
  max_tokens?: number;
  meta?: { n_ctx?: number };
  // mgmt reports this from the running profile's mmproj; llama-server itself never does
  input?: string[];
};

type ModelsResponse = {
  data?: LlamaCppModel[];
};

const DEFAULT_BASE_URL = "http://ubt26:3100/v1";
const DEFAULT_MODEL_ID = "qwopus3.6-35b-a3b-v1-gguf";

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

async function discoverModels(baseUrl: string): Promise<LlamaCppModel[]> {
  try {
    const response = await fetch(`${baseUrl}/models`, {
      signal: AbortSignal.timeout(1500),
    });

    if (!response.ok) return [];

    const payload = (await response.json()) as ModelsResponse;
    return Array.isArray(payload.data) ? payload.data.filter((model) => model.id) : [];
  } catch {
    return [];
  }
}

export default async function (pi: ExtensionAPI) {
  const baseUrl = normalizeBaseUrl(process.env.LLAMA_CPP_BASE_URL || DEFAULT_BASE_URL);
  const discoveredModels = await discoverModels(baseUrl);
  const models = discoveredModels.length > 0 ? discoveredModels : [{ id: DEFAULT_MODEL_ID }];

  pi.registerProvider("llama-cpp", {
    name: "llama.cpp",
    baseUrl,
    api: "openai-completions",
    apiKey: "llama.cpp",
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      // Must be true or pi records all-zero usage for every streamed turn, and
      // the compaction threshold check has no context size to work from.
      supportsUsageInStreaming: true,
      maxTokensField: "max_tokens",
      // Model is binary think/no-think; mgmt maps this to the runner's template.
      thinkingFormat: "qwen-chat-template",
    },
    models: models.map((model) => {
      const slotCtx = model.context_window ?? model.meta?.n_ctx ?? 131072;
      // pi already keeps prompt + max_tokens under contextWindow - 4096, so the
      // window can sit just under the slot; the 3% covers pi counting tokens with
      // a character estimate while the server counts them for real. These models
      // have no context shift, so overshooting n_ctx kills the turn outright.
      const contextWindow = Math.floor(slotCtx * 0.97);
      // mgmt owns this number (routes/models.py output_limit); the fallback is
      // only for a server too old to report it. It must stay under settings
      // compaction.reserveTokens (98304) minus pi-ai's CONTEXT_SAFETY_TOKENS
      // (4096): compaction only runs at turn boundaries (_checkCompaction fires
      // on agent_end and before a new prompt, never between tool-loop
      // iterations), so a whole tool loop has to fit in that gap. A loop longer
      // than it walks past contextWindow - 4096, where pi clamps max_tokens to 1
      // and every later request dies instantly.
      const maxTokens = 32768;
      return {
        id: model.id,
        name: model.name ?? `llama.cpp: ${model.id}`,
        reasoning: true,
        input: model.input ?? ["text"],
        contextWindow,
        maxTokens: model.max_tokens ?? maxTokens,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      };
    }),
  });

  pi.registerCommand("llama-cpp-status", {
    description: "Show llama.cpp provider endpoint and discovered model count",
    handler: async (_args, ctx) => {
      const count = discoveredModels.length;
      const source = count > 0 ? "discovered" : "fallback";
      ctx.ui.notify(`llama.cpp: ${baseUrl} (${models.length} ${source} model${models.length === 1 ? "" : "s"})`, "info");
    },
  });
}
