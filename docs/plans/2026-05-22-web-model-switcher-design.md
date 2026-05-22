# Web Model Switcher Design

## Goal

Add a model dropdown to the public Open WebUI page so the active `llama-server` model can be switched from the browser.

## Architecture

Move Open WebUI from port `3001` to `3002`. Run a new `local-llm-switcher` service on port `3001`, keeping Cloudflare Access unchanged at `llama.hehaw.net -> http://localhost:3001`.

The switcher service:

- Proxies normal Open WebUI traffic to `http://127.0.0.1:3002`.
- Injects a small dropdown/status widget into HTML responses.
- Provides switch APIs under `/api/local-llm/*`.
- Provides a fallback page at `/_switcher`.
- Writes `/home/cass/llama.cpp/current-model.env` atomically.
- Restarts `llama-server.service` with `systemctl --user restart llama-server.service`.
- Polls `http://127.0.0.1:8080/v1/models` until the expected alias is live.

## API

`GET /api/local-llm/models`

Returns allowed model/profile options. The list is explicit and does not accept arbitrary script paths from the browser.

`GET /api/local-llm/current`

Reads `current-model.env` and reports the matching model option plus live `/v1/models` status when available.

`POST /api/local-llm/switch`

Accepts `{ "id": "family:profile" }`, validates it against the allowlist, writes `current-model.env`, restarts the user service, waits for the selected alias, and returns the result.

## Model Allowlist

Initial options should cover installed reliable families:

- `qwen:reliable`
- `qwen-hauhau:reliable`
- `qwen-27b-hauhau:reliable`
- `gemma-hauhau:reliable`
- `qwen-27b:reliable`
- `qwen-coder:reliable`
- `gemma:reliable`
- `gemma-vision:reliable`
- `gpt-oss:reliable`
- `deepseek-r1:reliable`
- `qwen-opus:reliable`
- `qwen-heretic:reliable`

Each entry includes label, family, profile, script, alias, and whether it is multimodal.

## UI

Inject a compact fixed-position widget into Open WebUI pages:

- Dropdown with model labels.
- Switch button.
- Status text: current, restarting, ready, or error.
- Link to `/_switcher` fallback page.

The fallback page uses the same APIs and is useful if HTML injection fails after an Open WebUI update.

## Proxy Requirements

The proxy must preserve enough HTTP behavior for Open WebUI:

- Forward method, path, query, headers, and body.
- Support streaming responses instead of buffering all chat output.
- Avoid rewriting non-HTML responses.
- Filter hop-by-hop headers.

## Rollback

Rollback is simple:

- Stop/disable `local-llm-switcher.service`.
- Move Open WebUI back to port `3001`.
- Leave Cloudflare config unchanged.

## Security

Rely on Cloudflare Access as the public auth boundary. The switch endpoint still validates against a fixed allowlist and never executes browser-provided command strings.
