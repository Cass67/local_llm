# MTP Benchmark Design

## Goal

Re-benchmark the local_llm model set on `ubt26` after the llama.cpp update and promote MTP only where it is supported, stable, and useful on the RX 7900 XT.

## Approach

Use an MTP-first workflow where real MTP GGUF models exist, and keep current non-MTP models where no suitable equivalent is available. Avoid replacing reliable daily-driver profiles with weaker candidates just because they advertise MTP.

Initial candidate mapping:

| Current family | MTP path |
| --- | --- |
| `qwen` | Test `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` as direct replacement. |
| `qwen-27b` | Test `unsloth/Qwen3.6-27B-MTP-GGUF` as direct replacement. |
| `qwen-heretic` | Test `llmfan46/Qwen3.6-27B-uncensored-heretic-v2-Native-MTP-Preserved-GGUF`. |
| `qwen-opus` | Test `noctrex/Qwopus3.6-27B-v1-preview-MTP-GGUF` or `mudler/Qwopus3.6-35B-A3B-v1-APEX-MTP-GGUF` as nearest equivalents. |
| `qwen-coder` | No good 30B coder MTP equivalent found yet; only small coder-like candidates were found. |
| `gemma`, `gemma-vision` | No obvious MTP GGUF equivalent found. |
| `gpt-oss` | No obvious MTP GGUF equivalent found. |
| `deepseek-r1` | No useful 32B distill MTP equivalent found. |

## Benchmark Flow

Add a dedicated MTP benchmark runner rather than directly modifying launchers first. The runner will execute on `ubt26`, stop any current `llama-server`, start one candidate at a time with `--spec-type draft-mtp`, sweep `--spec-draft-n-max`, send a fixed OpenAI-compatible completion request, parse logs, and write CSV plus markdown results.

Start with conservative `--spec-draft-n-max` values: `2`, `4`, `8`, `12`, `16`, `24`, and `32`. Use existing profile context and batch values as the starting point.

Success means:

- server loads successfully
- completion request succeeds
- decode throughput improves or remains acceptable
- memory use fits without OOM or instability
- practical response quality remains acceptable

## Script And Profile Updates

Promote only candidates proven by benchmark results.

Planned updates:

- Add MTP/speculative flags per profile, not globally.
- Keep existing non-MTP profiles as fallback, especially `reliable` if MTP is unstable.
- For proven direct replacements, update relevant start scripts with the selected HF repo, quant, and `--spec-type draft-mtp --spec-draft-n-max <best>`.
- Leave families unchanged when no suitable MTP model exists and document the reason.
- Update `oc-local`, `configs/profiles.json`, README, installer symlinks, and tests only after winners are selected.

Likely profile policy:

- `speed`: most aggressive stable MTP setting.
- `fastlong` and `balanced`: safer MTP settings if they survive longer context.
- `reliable`: conservative MTP only if stable; otherwise retain non-MTP baseline.
- `tiny`: change only if long-context MTP is useful and stable.

## Test And Acceptance

Record, per candidate and setting:

- load status
- failure reason
- model, KV, recurrent/state, and compute buffers when available
- prompt tokens/sec
- decode tokens/sec
- baseline vs MTP delta

Select the highest `--spec-draft-n-max` that is stable and meaningfully faster. If higher values flatten or regress, choose the lower stable value. Do not promote a model that loads but fails completion. Do not promote a faster model with materially worse practical quality without explicit approval.

Verification:

- run shell syntax checks for changed scripts
- run existing `test_oc_local.sh`
- copy promoted launchers to `ubt26`
- perform at least one real server start for each promoted profile

## Outputs

- `docs/benchmarks/2026-05-18-mtp-benchmark.md`
- CSV benchmark results
- updated launcher/config/docs/tests for accepted MTP models
- documented list of unchanged families and reasons
