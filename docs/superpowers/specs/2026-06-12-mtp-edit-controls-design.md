# MTP Edit Controls Design

## Goal
Add first-class MTP speculative decoding controls to the web model edit modal so users do not need to hand-edit raw `flags` for common MTP options.

## Scope
In scope:
- Add an `Enable MTP speculative decoding` checkbox in `EditModelForm`.
- Show MTP fields only when enabled:
  - `Draft max` (`--spec-draft-n-max`), default `3`
  - `Draft min` (`--spec-draft-n-min`), default `1`
  - `P min` (`--spec-draft-p-min`), default `0.5`
- Preserve raw `Flags` for non-MTP advanced flags.
- Parse existing raw MTP flags on edit load, populate structured MTP fields, and remove those MTP flags from the visible raw flags value.
- Save structured MTP metadata under `config.mtp`.
- Render structured MTP into the llama-swap model command.
- Remove MTP flags from llama-swap config when MTP is disabled.
- Restart llama-swap when edit changes llama-swap config so reloaded models use current config.

Out of scope:
- Benchmarking MTP settings.
- Supporting speculative modes other than `draft-mtp`.
- Adding MTP controls outside model edit page.

## UI Design
Use a dedicated section in `EditModelForm`:

- Checkbox: `Enable MTP speculative decoding`
- When unchecked: MTP numeric fields hidden; save disables/removes MTP flags.
- When checked: show three inputs:
  - `Draft max`
  - `Draft min`
  - `P min`

Raw `Flags` remains below the MTP section and stores only non-MTP extras.

## Migration Behavior
When loading model detail:

1. Read `config.mtp` if present.
2. Also parse `config.flags` for these flags:
   - `--spec-type draft-mtp`
   - `--spec-draft-n-max <int>`
   - `--spec-draft-n-min <int>`
   - `--spec-draft-p-min <float>`
3. If raw MTP flags exist:
   - enable the MTP checkbox
   - fill values from raw flags, defaulting missing values to `3`, `1`, `0.5`
   - remove MTP tokens from the raw flags textbox in UI
4. On save, send structured MTP and cleaned raw flags.

## Backend Design
Extend edit request with optional `mtp` object:

```json
{
  "mtp": {
    "enabled": true,
    "draft_n_max": 3,
    "draft_n_min": 1,
    "draft_p_min": 0.5
  }
}
```

Backend saves it to accepted metadata under `config.mtp`.

When syncing llama-swap config:
- Remove previous MTP/spec-draft lines from the target model block.
- If `config.mtp.enabled` is true, insert:
  ```bash
  --spec-type draft-mtp --spec-draft-n-max N --spec-draft-n-min N --spec-draft-p-min P
  ```
- Append remaining non-MTP raw `config.flags` separately if present.
- Restart llama-swap after config changes.

## Error Handling
- Invalid numeric input should be rejected by browser number inputs where possible.
- Backend accepts missing MTP values and uses defaults only when enabled.
- If llama-swap config lacks the target model block, metadata still saves and launcher regeneration still runs; config sync is skipped.
- If Docker restart fails, edit endpoint returns an error so user knows live config was not applied.

## Tests
Use TDD.

Backend tests:
- Editing MTP saves `config.mtp` to metadata.
- Enabled MTP renders MTP flags into llama-swap config.
- Disabled MTP removes old MTP flags from llama-swap config.
- Non-MTP raw flags remain in llama-swap config.
- llama-swap restart is called when config changes.

Frontend tests/build checks:
- Extract helper functions for parsing/cleaning MTP flags so they can be unit tested.
- Raw flags containing MTP populate structured MTP values and return cleaned non-MTP flags.
- Saving sends structured `mtp` plus cleaned raw `flags`.
- `npm run build` passes.

## Acceptance Criteria
- User can enable MTP without typing raw flags.
- Existing raw MTP flags migrate into first-class fields.
- Reloaded Qwopus shows MTP flags in `/running` command.
- Completion timings include draft metrics when MTP is active.
