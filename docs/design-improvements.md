# local_llm Design Improvements

Goal:
- Make the repo easier to maintain, safer to change, and clearer to use.
- Provide checkboxes so you can pick what to adopt.

1. Centralized profiles/config

Purpose:
- Single source of truth for models, families, profiles, and llama-server settings.
- Reduce drift between oc-local, start*.sh, README, and tests.

Actions:
- [ ] Add configs/profiles.json:
  - [ ] Top-level:
    - [ ] "families": map of family → metadata
    - [ ] "profiles": map of "family:profile" → settings
  - [ ] Each profile includes:
    - [ ] model_family
    - [ ] model_path (GGUF)
    - [ ] context_length
    - [ ] quant_hint (if relevant)
    - [ ] batch_size / n_batch
    - [ ] cpu_offload / gpu_layers hint
    - [ ] extra_llama_args (array)
    - [ ] open_code_model_id
    - [ ] description (1-line for humans)

- [ ] Update oc-local:
  - [ ] Read from profiles.json instead of hard-coded branches.
  - [ ] Resolve:
    - [ ] family from command name or --family
    - [ ] profile from command name or --profile
  - [ ] Derive llama-server command from profile config.

- [ ] Update start*.sh:
  - [ ] Option A (preferred):
    - [ ] Thin wrappers:
      - [ ] source shared lib
      - [ ] call a shared function start_model_from_profile("qwen-heretic:reliable")
  - [ ] Option B (if you want fewer files):
    - [ ] Remove start*.sh; use:
      - [ ] "oc-local start qwen-heretic reliable" as the canonical command.

2. Streamline oc-local command model

Purpose:
- Make oc-local behavior consistent and discoverable.

Actions:
- [ ] Standardize usage:
  - [ ] oc-local <family> <profile> [flags]
  - [ ] Plus branded symlinks (oc-qwen-reliable, etc.) that prefill family/profile.

- [ ] Add explicit subcommands:
  - [ ] "oc-local list-profiles" → print available profiles and short descriptions.
  - [ ] "oc-local show <family> <profile>" → show config + command (like --info, but canonical).

- [ ] Flags:
  - [ ] --target local|remote:<host>
  - [ ] --lean (tune for speed, fewer safety margins)
  - [ ] --info (dry-run; show what would run)
  - [ ] --dry-run (no launch; show config + command)

- [ ] Ensure:
  - [ ] All symlinks map to this same interface; no special-casing outside profiles.json.

3. Model lifecycle via model-manager

Purpose:
- Clear flow from “interesting model” to “official profile”.

Actions:
- [ ] Define explicit pipeline:
  - [ ] candidate → benchmarked → accepted → wired

- [ ] Extend model-manager:
  - [ ] discover:
    - [ ] writes candidates into runs/candidates/<id>.json
  - [ ] select:
    - [ ] marks a candidate as “under consideration” in runs/selections/<id>.json
  - [ ] benchmark:
    - [ ] runs a benchmark (or wires to existing bench-*.sh)
    - [ ] stores results in runs/benchmarks/<id>.json
  - [ ] accept:
    - [ ] copies accepted config into profiles.json as a new profile
    - [ ] optionally:
      - [ ] creates/updates a startN.sh or registers as oc-local-only profile
      - [ ] suggests README updates (can be manual)
  - [ ] status:
    - [ ] shows counts and lists by stage (candidate/benchmarked/accepted)

- [ ] Update tests:
  - [ ] Add assertions that:
    - [ ] accepted profiles show up in "oc-local list-profiles"
    - [ ] status output matches runs/ contents

4. Remote environment centralization

Purpose:
- Make ubt26 environment and paths easy to adjust in one place.

Actions:
- [ ] Add configs/remote-env:
  - [ ] Exports:
    - [ ] ROCm env (e.g., HSA_OVERRIDE_GFX_VERSION, etc.)
    - [ ] LLAMA_CPP_DIR
    - [ ] MODELS_DIR
    - [ ] TEMPLATE_DIR
    - [ ] default port(s)

- [ ] Update oc-local and start*.sh:
  - [ ] On remote:
    - [ ] source remote-env before invoking llama-server.

- [ ] (Optional) Add scripts/remote-bootstrap.sh:
  - [ ] Ensures:
    - [ ] needed directories
    - [ ] symlinks / env file
    - [ ] minimal ROCm sanity check

5. Observability and run metadata

Purpose:
- Make it easy to reconstruct what ran, when, and with what config.

Actions:
- [ ] In oc-local, when launching:
  - [ ] Write a small run metadata file:
    - [ ] runs/runs/<timestamp>-<family>-<profile>.json
    - [ ] Fields:
      - [ ] family, profile
      - [ ] target (local/remote)
      - [ ] model_path
      - [ ] context_length
      - [ ] port
      - [ ] pid (if known)
      - [ ] command (abbreviated)

- [ ] Add "oc-local last-runs [n]" subcommand:
  - [ ] Prints last N runs in a compact table.

- [ ] Ensure:
  - [ ] runs/ is gitignored (already is) and stable in structure.

6. Testing and consistency

Purpose:
- Ensure changes are safe and docs stay correct.

Actions:
- [ ] Extend test_oc_local.sh:
  - [ ] Validate:
    - [ ] A known profile in profiles.json matches oc-local --info output.
    - [ ] "oc-local list-profiles" includes expected families.
    - [ ] model-manager status reflects runs/ directory.

- [ ] Add static checks:
  - [ ] bash -n for all scripts
  - [ ] shellcheck (if available) for oc-local and helpers

- [ ] README:
  - [ ] Add short ASCII diagram:
    - [ ] Mac (OpenCode) → oc-local → SSH → ubt26 (llama-server) → model
  - [ ] Clarify:
    - [ ] When to use each profile (“reliable”, “lean”, etc.)

7. Optional: Reduce boilerplate in scripts

Purpose:
- DRY up shell scripts without losing readability.

Actions:
- [ ] Add scripts/lib.sh:
  - [ ] Shared functions:
    - [ ] log_info, log_err
    - [ ] resolve_target (local vs remote)
    - [ ] run_remote_ssh
    - [ ] wait_for_api

- [ ] Update:
  - [ ] oc-local, model-discovery, model-manager, update-manager, hardware-analyzer to source lib.sh.
