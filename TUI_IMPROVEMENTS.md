# Model-Manager TUI Improvement Plan

## 1. UI/UX Enhancements
- [x] **Main Menu**: Replace static labels with a more interactive `ListView` or button-based navigation.
- [x] **Theme**: Implement a consistent color palette and border style across all screens.
- [x] **Navigation**: Add breadcrumbs for deep navigation (InstallProgressScreen, HFCardScreen, SearchScreen, RunScreen, StatusScreen, etc.)

## 2. Search Improvements
- [x] **Sort/Filter**: Sort by score/repo/quant; filter by keyword.
- [x] **Pagination**: 15/page, ← → navigation.

## 3. Install Flow Improvements
- [x] **Customization**: Allow `ctx` and `profile` selection before install/benchmark.
- [x] **Batch Install**: Multi-select (`m` / Space), Enter to batch install selected candidates via `BatchInstallScreen`.
- [x] **Real-time Logs**: Streaming log window in `InstallProgressScreen`; auto-scroll; line-count indicator.

## 4. Run/Management Improvements
- [x] **Server Status**: Health checks for `Running` / `Stopped`.
- [x] **Server Control**: `x` to stop server.
- [x] **Runtime Overrides**: Temporary `ctx` override per run.
- [x] **Current Model on Status**: Show which model is currently running.

## 5. List & Delete Improvements
- [x] **Detail View**: `d` for full metadata + benchmark results.
- [x] **Confirmation Dialogs**: Prompts before delete.
- [x] **Quick Run**: `r` from List screen.
- [x] **Edit Model**: `e` for per-model editor (profile, ctx, flags); live command preview; `update-launcher` on save.

## 6. Technical Refactoring
- [x] **Error Handling**: Replaced all broad `except Exception` with specific types (`ValueError`, `RuntimeError`, `OSError`, `LookupError`, `IndexError`, `subprocess.CalledProcessError`).
- [x] **Architecture**: Service layer (`service.py`) extracted from TUI; subprocess/SSH removed from `tui.py`; clean UI/I/O separation.
- [x] **Configuration**: Central config (`config.py`) for paths, scripts, profiles; imported by `commands.py`, `state.py`, `service.py`, `tui.py`.

## Implementation history

### First-pass (2026-06-09)
- Selectable table navigation + number-key shortcuts.
- `r` quick-run on ListScreen.
- `x` stop-server on RunScreen.
- Status screen shows remote `llama-server.service` health.
- Delete screen requires confirmation.

### Second-pass (2026-06-09)
- Search: sort/filter/pagination.
- Install logs: real-time scrollable DataTable.
- Detail view (`d`).
- Full CSS theme overhaul.
- Error handling: specific types.
- Runtime overrides (`o`).
- Batch install: Space + B.

### Third-pass (2026-06-10)
- Edit Model (`e`) with live command preview.
- `update-launcher` command in `model-manager.sh`.
- Current running model on StatusScreen.

### Fourth-pass (2026-06-11) — tui-improvements
- Breadcrumbs across deep screens.
- Batch install refined: Enter triggers batch when multi-select active.
- Install logs: streaming tail, auto-scroll, line-count.
- Architecture refactor: `service.py` extracted; `tui.py` no subprocess/SSH.
- Config centralization: `config.py` single source of truth.
- Lint/typecheck: ruff clean, bandit low-severity only.
- Tests: 32/32 passing.
