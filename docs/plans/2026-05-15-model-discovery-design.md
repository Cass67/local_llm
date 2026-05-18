# Model Discovery Design

## Goal

Make `model-discovery` a real Hugging Face discovery tool while keeping the tuned local fleet visible. The default command should query Hugging Face live, detect the actual model host hardware, and rank candidates for the RX 7900 XT setup.

## Scope

- Default hardware target is `OC_LOCAL_REMOTE_HOST`, falling back to `ubt26`.
- Default discovery mode performs live Hugging Face search.
- Installed/tuned profiles remain visible in a separate section.
- Existing local and remote host override behavior remains available.
- No automatic model downloads or launcher rewrites in this phase.

## Command Shape

```bash
model-discovery
model-discovery --query "qwen coder gguf"
model-discovery --limit 10
model-discovery --installed-only
model-discovery --local
model-discovery --host ubt26
```

## Output Sections

### Hardware

The hardware section should represent the machine that will run `llama-server`, not just the Mac client.

Fields:

- hardware source: `remote:<host>` or `local`
- CPU cores
- RAM GiB
- GPU name
- VRAM MiB/GiB
- ROCm target when available, for example `gfx1100`

GPU detection should try multiple sources, in order:

1. `rocminfo` for marketing name and ROCm target.
2. `rocm-smi` for VRAM if parseable.
3. `llama-server --list-devices` from the configured remote llama.cpp directory as fallback.

If a field cannot be detected, print `unknown` for that field only. Do not let one missing command hide the rest of the hardware data.

### Hugging Face Candidates

Default search should query Hugging Face live for GGUF repositories suitable for `llama.cpp`.

Candidate rows should include:

- repo id
- model family or title when available
- likely purpose: code, reasoning, chat, vision, or unknown
- available quant hint when inferable from repo names/files
- estimated fit: likely, maybe, unlikely, or unknown
- short reason for the fit estimate
- suggested first test command shape, not an automatic install

Ranking should prefer:

- GGUF repositories
- models likely to fit 20 GiB VRAM with useful context
- code and reasoning models relevant to OpenCode
- recent or popular repos when Hugging Face returns enough metadata

Default query can be broad, for example GGUF code reasoning chat models. `--query` should override it.

### Already Tuned Profiles

Keep the current installed fleet as a separate section named `Already Tuned Profiles`.

Profiles:

- `qwen`: `oc-qwen-reliable --lean`
- `qwen-coder`: `oc-qwen-coder-reliable --lean`
- `gpt-oss`: `oc-gpt-oss-speed --lean`
- `gemma`: `oc-gemma-reliable --lean`
- `gemma-vision`: `oc-gemma-vision-reliable --lean`
- `qwen-27b`: `oc-qwen-27b-reliable --lean`, plus `oc-qwen-27b-long --lean`
- `deepseek-r1`: `oc-deepseek-r1-reliable --lean`

This section is inventory, not search results.

## Error Handling

- If Hugging Face is unreachable, print the hardware and tuned fleet sections, then a clear warning for search failure.
- If SSH to the remote host fails, fall back to local hardware and label the fallback clearly.
- If optional GPU tools are missing, continue with partial hardware data.
- Avoid hard failures except for invalid command-line arguments.

## Testing

- Add tests for CLI wording and options.
- Test `--installed-only` without network.
- Test remote fallback by setting `OC_LOCAL_REMOTE_HOST=__none__`.
- Test Hugging Face parsing with a fixture or injectable response file so tests do not require live network.
- Keep syntax and ShellCheck verification for changed shell scripts.

## Non-Goals

- No automatic GGUF downloads.
- No automatic profile generation.
- No benchmark claims without running `llama-server`.
- No changes to `oc-local` model launch behavior.
