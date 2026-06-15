"""TUI entry point for model-manager using Textual."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Markdown

from .config import HF_CACHE_ROOT, PROFILES, SCRIPT_DIR
from .service import (
    cancel_remote_processes,
    check_remote_vram,
    delete_model,
    detect_running_model,
    get_delete_list,
    get_download_size_bytes,
    get_local_disk_models,
    get_remote_disk_models,
    get_remote_downloads,
    get_server_status,
    remote_inventory,
    run_model_discovery,
    select_best_quant,
    start_server,
    stop_server,
)
from .state import (
    get_target,
    has_default,
    list_accepted,
    load_candidates,
    read_config,
    save_candidates,
    write_config,
)
from .tui_helpers import (
    filter_candidates,
    paginate_candidates,
    sort_candidates,
)


def build_list_rows(
    accepted: list[tuple[str, dict[str, Any]]],
    inventory: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Build rows for list screen: accepted + disk-only."""
    rows: list[dict[str, str]] = []
    accepted_repos: set[str] = set()
    for family, data in sorted(accepted, key=lambda x: x[0]):
        repo = str(data.get("repo") or data.get("hf_repo") or "")
        accepted_repos.add(repo)
        rows.append(
            {
                "source": "accepted",
                "family": family,
                "alias": str(data.get("alias") or "?"),
                "repo": repo,
                "file": str(data.get("hf_file") or data.get("quant") or "?"),
                "profile": str(data.get("profile") or "?"),
                "ctx": str((data.get("config") or {}).get("ctx") or "?"),
            }
        )
    for item in inventory:
        repo = item.get("repo", "")
        if repo in accepted_repos:
            continue
        rows.append(
            {
                "source": "disk-only",
                "family": repo,
                "alias": "not accepted",
                "repo": repo,
                "file": item.get("file") or Path(item.get("path") or "").name or "?",
                "profile": "-",
                "ctx": "-",
            }
        )
    return rows


def _breadcrumb_label(parts: list[str]) -> Label:
    """Create a breadcrumb navigation label."""
    text = " ".join(f"{p}" if i == 0 else f"› {p}" for i, p in enumerate(parts))
    return Label(f"[dim]{text}[/dim]")


class MainMenu(Screen[None]):
    """Main menu screen with navigation options."""

    BINDINGS = [
        Binding("1", "init", "Init"),
        Binding("2", "search", "Search"),
        Binding("3", "install", "Install"),
        Binding("4", "list", "List"),
        Binding("5", "delete", "Delete"),
        Binding("6", "run", "Run"),
        Binding("7", "status", "Status"),
        Binding("8", "check_updates", "Check Updates"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("╔══════════════════════════════════════╗", classes="title"),
            Label("║        model-manager TUI             ║", classes="title"),
            Label("╚══════════════════════════════════════╝", classes="title"),
            Label(""),
            Label("  [bold]1[/]  Init          Set target (local or remote:<host>)"),
            Label("  [bold]2[/]  Search        Search and score models"),
            Label("  [bold]3[/]  Install       Install a candidate by index"),
            Label("  [bold]4[/]  List          List accepted models"),
            Label("  [bold]5[/]  Delete        Delete an accepted model"),
            Label("  [bold]6[/]  Run           Run a model server"),
            Label("  [bold]7[/]  Status        Show model-manager status"),
            Label("  [bold]8[/]  Check Updates Check for model updates"),
            Label("  [bold]q[/]  Quit"),
            id="menu-container",
        )
        yield Footer()

    def action_init(self) -> None:
        self.app.push_screen(InitScreen())

    def action_search(self) -> None:
        self.app.push_screen(SearchScreen())

    def action_install(self) -> None:
        self.app.push_screen(InstallScreen())

    def action_list(self) -> None:
        self.app.push_screen(ListScreen())

    def action_delete(self) -> None:
        self.app.push_screen(DeleteScreen())

    def action_run(self) -> None:
        self.app.push_screen(RunScreen())

    def action_status(self) -> None:
        self.app.push_screen(StatusScreen())

    def action_check_updates(self) -> None:
        self.app.push_screen(CheckUpdatesScreen())


class InitScreen(Screen[None]):
    """Screen to initialize target."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        current = get_target()
        target_text = f"[green]{current}[/green]" if current else "[red]not set[/red]"

        yield Container(
            Label("[bold]Initialize Target[/bold]"),
            Label(""),
            Label(f"  Current target: {target_text}"),
            Label(""),
            Label("  Enter target (local or remote:<host>):"),
            Input(placeholder="remote:gpu-host", id="target-input"),
        )
        yield Footer()

    def on_mount(self) -> None:
        inp = self.query_one("#target-input", Input)
        current = get_target()
        if current:
            inp.value = current
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "target-input":
            return
        target = event.value.strip()
        if not target:
            self.app.notify("Target required", severity="error")
            return
        try:
            write_config(target)
            self.app.notify(f"Initialized: target={target}")
        except SystemExit as e:
            self.app.notify(str(e), severity="error")
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


class HFCardScreen(Screen[None]):
    """Show a Hugging Face model card."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("up", "scroll_up", "Up", show=False),
        Binding("down", "scroll_down", "Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("home", "scroll_home", "Top", show=False),
        Binding("end", "scroll_end", "Bottom", show=False),
    ]

    def __init__(self, repo: str) -> None:
        super().__init__()
        self.repo = repo

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "Search", f"HF: {self.repo[:40]}"])
        yield Label(f"[bold]Hugging Face Card[/bold]  {self.repo}")
        yield Label("Loading...", id="hf-card-status")
        card = Markdown("", id="hf-card-markdown")
        card.can_focus = True
        card.styles.height = "1fr"
        card.styles.overflow_y = "scroll"
        yield card
        yield Footer()

    def on_mount(self) -> None:
        def _finish_ok(markdown: str) -> None:
            self.query_one("#hf-card-status", Label).update(
                f"[green]https://huggingface.co/{self.repo}[/green]"
            )
            card = self.query_one("#hf-card-markdown", Markdown)
            card.update(markdown)
            card.focus()

        def _finish_error(message: str) -> None:
            self.query_one("#hf-card-status", Label).update(f"[red]{message}[/red]")
            self.query_one("#hf-card-markdown", Markdown).update(
                f"Open manually: https://huggingface.co/{self.repo}"
            )

        def _run() -> None:
            encoded_repo = urllib.parse.quote(self.repo, safe="/")
            url = f"https://huggingface.co/{encoded_repo}/raw/main/README.md"
            try:
                with urllib.request.urlopen(url, timeout=20) as response:  # nosec: B310
                    body = response.read().decode("utf-8", errors="replace")
                if not body.strip():
                    self.app.call_from_thread(_finish_error, "Model card is empty")
                    return
                self.app.call_from_thread(_finish_ok, body)
            except (OSError, UnicodeDecodeError) as e:
                self.app.call_from_thread(_finish_error, f"Could not fetch card: {e}")

        self.query_one("#hf-card-markdown", Markdown).focus()
        self.run_worker(_run, thread=True)

    def _card(self) -> Markdown:
        return self.query_one("#hf-card-markdown", Markdown)

    def action_scroll_up(self) -> None:
        self._card().scroll_up(animate=False)

    def action_scroll_down(self) -> None:
        self._card().scroll_down(animate=False)

    def action_page_up(self) -> None:
        self._card().scroll_page_up(animate=False)

    def action_page_down(self) -> None:
        self._card().scroll_page_down(animate=False)

    def action_scroll_home(self) -> None:
        self._card().scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        self._card().scroll_end(animate=False)

    def action_back(self) -> None:
        self.app.pop_screen()


class SearchScreen(Screen[None]):
    """Screen to search for models."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("i", "hf_card", "HF Card"),
        Binding("space", "toggle_select", "Toggle Select"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("m", "toggle_multi", "Multi"),
        Binding("left", "prev_page", "Prev"),
        Binding("right", "next_page", "Next"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._searching = False
        self._spinner_idx = 0
        self._all_candidates: list[dict[str, Any]] = []
        self._sort_modes = ["score", "repo", "quant"]
        self._sort_mode_index = 0
        self._page = 1
        self._per_page = 15
        self._multi_select = False
        self._selected: set[int] = set()

    def action_cycle_sort(self) -> None:
        self._sort_mode_index = (self._sort_mode_index + 1) % len(self._sort_modes)
        self._render_results()

    def action_prev_page(self) -> None:
        if self._page > 1:
            self._page -= 1
            self._render_results()

    def action_next_page(self) -> None:
        total = len(self._get_filtered_candidates())
        max_page = (total + self._per_page - 1) // self._per_page if total else 1
        if self._page < max_page:
            self._page += 1
            self._render_results()

    def action_toggle_multi(self) -> None:
        self._multi_select = not self._multi_select
        mode = (
            "Multi-Select ON (Space=select, Enter=batch install)"
            if self._multi_select
            else "Multi-Select OFF"
        )
        self.app.notify(mode)
        self._render_results()

    def action_toggle_select(self) -> None:
        if not self._multi_select:
            # In single-select mode, Space opens HF card
            self.action_hf_card()
            return
        table = self.query_one("#results-table", DataTable)
        row = table.cursor_row
        if row is None:
            return
        # Map visual row to candidate index (page-based)
        filtered = self._get_filtered_candidates()
        mode = self._sort_modes[self._sort_mode_index]
        sorted_list = sort_candidates(filtered, mode)
        _, _, paged = paginate_candidates(sorted_list, self._page, self._per_page)
        if row < 0 or row >= len(paged):
            return
        idx = (self._page - 1) * self._per_page + row
        if idx in self._selected:
            self._selected.discard(idx)
        else:
            self._selected.add(idx)
        self._render_results()

    def action_batch_install(self) -> None:
        if not self._selected:
            self.app.notify("No models selected", severity="warning")
            return
        filtered = self._get_filtered_candidates()
        mode = self._sort_modes[self._sort_mode_index]
        sorted_list = sort_candidates(filtered, mode)
        queue: list[dict[str, Any]] = []
        for idx in sorted(self._selected):
            if 0 <= idx < len(sorted_list):
                queue.append(sorted_list[idx])
        if not queue:
            self.app.notify("No valid selections", severity="warning")
            return
        self.app.push_screen(BatchInstallScreen(queue))

    def _get_filtered_candidates(self) -> list[dict[str, Any]]:
        filter_text = ""
        try:
            filter_input = self.query_one("#filter-input", Input)
            filter_text = (filter_input.value or "").strip()
        except TypeError:
            pass
        return filter_candidates(self._all_candidates, filter_text)

    def _render_results(self) -> None:
        filtered = self._get_filtered_candidates()
        mode = self._sort_modes[self._sort_mode_index]
        sorted_list = sort_candidates(filtered, mode)
        self._page, total_pages, paged = paginate_candidates(
            sorted_list, self._page, self._per_page
        )

        table = self.query_one("#results-table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Repo", "Score", "Quant")
        table.cursor_type = "row"

        total = len(filtered)
        base_idx = (self._page - 1) * self._per_page

        for i, c in enumerate(paged, 1):
            quant = c.get("best_quant", "?")
            idx = base_idx + i - 1
            prefix = "• " if (self._multi_select and idx in self._selected) else ""
            table.add_row(prefix + str(i), c["repo"], str(c["score"]), quant)

        if paged:
            table.move_cursor(row=0, column=0)
            table.focus()

        status = self.query_one("#search-status", Label)
        multi_hint = f" ({len(self._selected)} selected)" if self._multi_select else ""
        status.update(
            f"[green]Found {total} candidates[/green] "
            f"(page {self._page}/{total_pages}, sort: {mode})" + multi_hint
        )

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "Search"])
        yield Label("[bold]Search Models[/bold]")
        yield Label("")
        yield Label(
            "  Enter search query (Enter installs, i/Space=HF card, m=multi-select, "
            "s sort, left/right page, filter below):"
        )
        yield Input(placeholder="coding gguf", id="query-input")
        yield Input(placeholder="filter by repo/quant (optional)", id="filter-input")
        yield Label("", id="search-status")
        yield DataTable(id="results-table")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#query-input", Input).focus()
        table = self.query_one("#results-table", DataTable)
        table.add_columns("#", "Repo", "Score", "Quant")
        table.cursor_type = "row"
        self.set_interval(0.2, self._tick_spinner)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input" and self._all_candidates:
            self._page = 1
            self._render_results()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "query-input":
            return
        query = event.value.strip() or "coding gguf"
        self._do_search(query)

    def _tick_spinner(self) -> None:
        if not self._searching:
            return
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._spinner_idx = (self._spinner_idx + 1) % len(frames)
        self.query_one("#search-status", Label).update(
            f"[yellow]{frames[self._spinner_idx]} Searching...[/yellow]"
        )

    def _do_search(self, query: str) -> None:
        target = get_target()
        if not target:
            self.app.notify("Not initialized — run Init first", severity="error")
            return

        status = self.query_one("#search-status", Label)
        self._searching = True
        status.update("[yellow]⠋ Searching...[/yellow]")

        def _finish_ok(ranked: list[dict[str, Any]]) -> None:
            self._searching = False
            save_candidates(ranked)
            self._all_candidates = ranked
            self._page = 1
            self._render_results()
            self.app.notify(f"Saved {len(ranked)} candidates")

        def _finish_error(message: str) -> None:
            self._searching = False
            status.update(f"[red]{message}[/red]")
            self.app.notify(message, severity="error")

        def _run() -> None:
            try:
                ranked = run_model_discovery(query, target)
                if not ranked:
                    self.app.call_from_thread(_finish_error, "No candidates found")
                    return
                self.app.call_from_thread(_finish_ok, ranked)
            except (ValueError, RuntimeError, OSError) as e:
                self.app.call_from_thread(_finish_error, str(e))

        self.run_worker(_run, thread=True)

    def _selected_candidate(self) -> dict[str, Any] | None:
        table = self.query_one("#results-table", DataTable)
        candidates = load_candidates() or []
        cursor = table.cursor_row
        if cursor < 0 or cursor >= len(candidates):
            return None
        return candidates[cursor]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "results-table":
            return
        # In multi-select mode with selections, Enter triggers batch install
        if self._multi_select and self._selected:
            self.action_batch_install()
            return
        candidate = self._selected_candidate()
        if not candidate:
            return
        self.app.push_screen(InstallProgressScreen(event.cursor_row + 1, candidate))

    def action_hf_card(self) -> None:
        candidate = self._selected_candidate()
        if not candidate:
            self.app.notify("No search result selected", severity="warning")
            return
        repo = candidate.get("repo")
        if not isinstance(repo, str) or not repo:
            self.app.notify("Selected result has no repo", severity="error")
            return
        self.app.push_screen(HFCardScreen(repo))

    def action_back(self) -> None:
        self.app.pop_screen()


class InstallScreen(Screen[None]):
    """Screen to install a model."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        body: list[Any] = [Label("[bold]Install Model[/bold]"), Label("")]
        body.append(Label("  Select model, Enter installs it"))
        body.append(Label(""))
        body.append(DataTable(id="install-table"))
        yield Container(*body)
        yield Footer()

    def _disk_models(self) -> list[dict[str, str]]:
        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            return []
        try:
            inventory = remote_inventory(host)
        except (OSError, TimeoutError):
            return []
        rows: list[dict[str, str]] = []
        for entry in inventory:
            repo = str(entry.get("repo") or "")
            file = str(entry.get("file") or "")
            if not repo:
                continue
            if not file:
                rows.append(
                    {
                        "kind": "cache-dir",
                        "repo": repo,
                        "file": "",
                        "score": "no-gguf",
                        "quant": "missing",
                    }
                )
            else:
                quant = Path(file).stem or "unknown"
                rows.append(
                    {
                        "kind": "disk",
                        "repo": repo,
                        "file": file,
                        "score": "disk",
                        "quant": quant,
                    }
                )
        return rows

    def on_mount(self) -> None:
        table = self.query_one("#install-table", DataTable)
        table.add_columns("#", "Source", "Repo", "File", "Score", "Quant")
        self._entries: list[dict[str, str]] = []
        for c in load_candidates() or []:
            self._entries.append(
                {
                    "kind": "search",
                    "repo": str(c.get("repo", "")),
                    "file": str(c.get("best_file", "")),
                    "score": str(c.get("score", "?")),
                    "quant": str(c.get("best_quant", "?")),
                }
            )
        disk_by_repo = {entry["repo"]: entry for entry in self._disk_models()}
        search_repos = {entry["repo"] for entry in self._entries}
        for entry in self._entries:
            disk = disk_by_repo.get(entry["repo"])
            if disk and disk.get("file"):
                entry["kind"] = "search+disk"
                # Prefer already-downloaded GGUF over searched best_file.
                entry["file"] = disk["file"]
                entry["quant"] = disk.get("quant", entry["quant"])
        for repo, entry in disk_by_repo.items():
            if repo not in search_repos:
                self._entries.append(entry)
        for i, entry in enumerate(self._entries, 1):
            table.add_row(
                str(i), entry["kind"], entry["repo"], entry["file"], entry["score"], entry["quant"]
            )
        if self._entries:
            table.cursor_type = "row"
            table.move_cursor(row=0, column=0)
            table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "install-table":
            return
        table = self.query_one("#install-table", DataTable)
        cursor = table.cursor_row
        if cursor is None or cursor < 0 or cursor >= len(self._entries):
            return
        entry = self._entries[cursor]
        target = get_target()
        if not target or not target.startswith("remote:"):
            self.app.notify("Install requires remote target", severity="error")
            return
        self.app.push_screen(InstallProgressScreen(cursor + 1, entry))

    def action_back(self) -> None:
        self.app.pop_screen()


class InstallProgressScreen(Screen[None]):
    """Screen showing install progress: download → benchmark → results → accept/reject."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, index: int, chosen: dict) -> None:
        super().__init__()
        self.index = index
        self.chosen = chosen
        self.result: dict | None = None
        self.cancelled = False
        self._busy = False
        self._phase = ""
        self._transfer = ""
        self._spinner_idx = 0
        self._accepting = False
        self._load_failed = False
        from .tui_helpers import create_install_log_lines

        self._log = create_install_log_lines(max_lines=200)

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "Search", "Installing"])
        yield Container(
            Label("[bold]Install Progress[/bold]"),
            Label(""),
            Label(f"  Candidate: [bold]{self.chosen['repo']}[/bold]"),
            Label(""),
            Label("  Status:", id="status-label"),
            Label("", id="detail-label"),
            DataTable(id="install-action-table"),
            Label("[dim]Install Log (live tail):[/dim]", id="log-header"),
            DataTable(id="install-log-table"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick_install_spinner)
        self.set_interval(0.5, self._refresh_log_table)
        self.run_worker(self._install_worker, thread=True)

    def _refresh_log_table(self) -> None:
        table = self.query_one("#install-log-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Time", "Message")
        for entry in self._log:
            ts = entry.get("time", 0)
            text = entry.get("text", "")
            if ts:
                from datetime import datetime

                t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            else:
                t = ""
            table.add_row(t, text)
        # Auto-scroll to latest line
        if self._log and len(table.rows) > 0:
            table.move_cursor(row=len(table.rows) - 1, column=0)
        # Show tail indicator when log is large
        if len(self._log) > 50:
            try:
                self.query_one("#log-header", Label).update(
                    f"[dim]Install Log (live tail · {len(self._log)} lines)[/dim]"
                )
            except (LookupError, RuntimeError):
                pass

    def _set_busy(self, busy: bool, phase: str = "", transfer: str = "") -> None:
        self._busy = busy
        self._phase = phase
        self._transfer = transfer
        if not busy and phase:
            self.query_one("#status-label", Label).update(phase)

    def _tick_install_spinner(self) -> None:
        if not self._busy:
            return
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._spinner_idx = (self._spinner_idx + 1) % len(frames)
        suffix = f"  {self._transfer}" if self._transfer else ""
        self.query_one("#status-label", Label).update(
            f"[yellow]{frames[self._spinner_idx]} {self._phase}{suffix}[/yellow]"
        )

    def _install_worker(self):  # noqa: C901
        """Worker that runs install and yields progress."""
        from .commands import (
            _download_on_host,
            _infer_alias,
            _infer_family,
            _read_benchmark_summary,
            _run_benchmark,
        )
        from .tui_helpers import append_install_log_line

        status = self.query_one("#status-label", Label)
        detail = self.query_one("#detail-label", Label)
        append_install_log_line(self._log, "Install started", max_lines=200)

        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            self.app.call_from_thread(status.update, "[red]Install requires remote target[/red]")
            self.app.notify("Install requires remote target", severity="error")
            return

        repo = self.chosen.get("repo", "")
        hf_file = self.chosen.get("file") or self.chosen.get("best_file", "")
        quant = self.chosen.get("quant") or self.chosen.get("best_quant", "unknown") or "unknown"
        if not hf_file:
            self.app.call_from_thread(self._set_busy, True, "Resolving GGUF")
            try:
                import urllib.parse
                import urllib.request

                encoded = urllib.parse.quote(repo, safe="/")
                with urllib.request.urlopen(  # nosec B310
                    f"https://huggingface.co/api/models/{encoded}/tree/main", timeout=20
                ) as response:
                    tree = json.load(response)
                siblings: list[dict[str, Any]] = []
                for item in tree if isinstance(tree, list) else []:
                    if not isinstance(item, dict):
                        continue
                    path = item.get("path") or item.get("rfilename")
                    size = item.get("size")
                    if (
                        isinstance(path, str)
                        and path.lower().endswith(".gguf")
                        and isinstance(size, int | float)
                    ):
                        siblings.append({"rfilename": path, "size": size})
                vram_gb = check_remote_vram(host)
                hf_file, quant = select_best_quant(repo, host, siblings, vram_gb)
            except (ValueError, RuntimeError, OSError) as e:
                self.app.call_from_thread(status.update, "[red]No GGUF file found[/red]")
                self.app.call_from_thread(detail.update, f"  Could not resolve GGUF: {e}")
                self.app.notify("No GGUF file found for cached repo", severity="error")
                self.app.call_from_thread(self._set_busy, False)
                return
        if not hf_file:
            self.app.call_from_thread(status.update, "[red]No GGUF file found[/red]")
            self.app.call_from_thread(detail.update, "  HF repo has no GGUF file to download.")
            self.app.notify("No GGUF file found for cached repo", severity="error")
            self.app.call_from_thread(self._set_busy, False)
            return
        profile = "balanced"
        ctx = "131072"
        family = _infer_family(repo)
        alias = _infer_alias(repo)

        self.app.call_from_thread(self._set_busy, True, "Downloading")
        self.app.call_from_thread(detail.update, f"  Repo: {repo}")
        append_install_log_line(self._log, f"Downloading {repo}", max_lines=200)

        import threading
        import time

        stop_monitor = threading.Event()

        def _monitor_download() -> None:
            repo_dir = "models--" + repo.replace("/", "--")
            last_bytes: int | None = None
            last_time = time.monotonic()
            speed_ema = 0.0
            idle_ticks = 0
            while not stop_monitor.is_set():
                try:
                    size_bytes = get_download_size_bytes(host, HF_CACHE_ROOT / repo_dir) or (
                        last_bytes or 0
                    )
                except OSError:
                    size_bytes = last_bytes or 0
                now = time.monotonic()
                total = size_bytes / 1_000_000_000
                if last_bytes is None:
                    last_bytes = size_bytes
                    last_time = now
                    self.app.call_from_thread(
                        self._set_busy,
                        True,
                        "Downloading",
                        f"calculating...  {total:.1f} GB",
                    )
                    stop_monitor.wait(1.0)
                    continue
                elapsed = max(now - last_time, 0.001)
                delta = max(size_bytes - last_bytes, 0)
                inst_speed = delta / elapsed / 1_000_000
                if delta > 0:
                    idle_ticks = 0
                    speed_ema = (
                        inst_speed if speed_ema <= 0 else (0.25 * inst_speed + 0.75 * speed_ema)
                    )
                else:
                    idle_ticks += 1
                    if idle_ticks >= 8:
                        speed_ema *= 0.8
                self.app.call_from_thread(
                    self._set_busy,
                    True,
                    "Downloading",
                    f"{speed_ema:.1f} MB/s  {total:.1f} GB",
                )
                last_bytes = size_bytes
                last_time = now
                stop_monitor.wait(1.0)

        monitor_thread = threading.Thread(target=_monitor_download, daemon=True)
        monitor_thread.start()

        try:
            if not _download_on_host(host, repo, hf_file):
                result = {"status": "error", "message": "download failed"}
            else:
                stop_monitor.set()
                self.app.call_from_thread(self._set_busy, True, "Stopping server")
                append_install_log_line(self._log, "Stopping running server", max_lines=200)
                stop_server(f"remote:{host}")
                self.app.call_from_thread(self._set_busy, True, "Benchmarking")
                benchmark_file = _run_benchmark(
                    host, repo, family, alias, profile, quant, hf_file, ctx
                )
                if not benchmark_file:
                    result = {"status": "error", "message": "benchmark failed"}
                else:
                    summary = _read_benchmark_summary(benchmark_file)
                    result = {
                        "status": "benchmark_done",
                        "family": family,
                        "alias": alias,
                        "benchmark_file": benchmark_file,
                        "benchmark_summary": summary,
                        "message": f"benchmark complete for {family}",
                    }
        except (RuntimeError, ValueError, OSError) as e:
            result = {"status": "error", "message": str(e)}
        finally:
            stop_monitor.set()

        if self.cancelled:
            self.app.call_from_thread(self._set_busy, False)
            return

        if result["status"] == "error":
            self.app.call_from_thread(self._set_busy, False)
            self.app.call_from_thread(status.update, f"[red]Failed: {result['message']}[/red]")
            self.app.notify(f"Install failed: {result['message']}", severity="error")
            self.app.call_from_thread(self.app.pop_screen)
            return

        if result["status"] == "benchmark_done":
            self.app.call_from_thread(self._set_busy, False)
            self.app.call_from_thread(self._show_benchmark_done, result)
            return

        self.app.call_from_thread(
            status.update, f"[yellow]{result.get('message', 'Unknown')}[/yellow]"
        )

    def _show_benchmark_done(self, result: dict) -> None:
        from .tui_helpers import append_install_log_line

        self.result = result
        summary = cast(dict, result.get("benchmark_summary", {}))
        load_status = summary.get("load_status", "")
        self._load_failed = bool(load_status and load_status != "success")
        load_failed = self._load_failed

        if load_failed:
            self.query_one("#status-label", Label).update(
                f"[red]Benchmark: load failed ({load_status})[/red]"
            )
            append_install_log_line(
                self._log, f"Benchmark complete — load failed: {load_status}", max_lines=200
            )
        else:
            self.query_one("#status-label", Label).update("[green]Benchmark complete[/green]")
            append_install_log_line(self._log, "Benchmark complete", max_lines=200)

        lines = [f"  Family: {result.get('family', '?')}"]
        if load_failed:
            lines.append(f"  [red]Load failed: {load_status}[/red]")
            lines.append("  [dim]Model could not be loaded — accept will fail[/dim]")
        else:
            if summary.get("prompt_tok_s") is not None:
                lines.append(f"  Prompt tok/s: {summary['prompt_tok_s']}")
            if summary.get("decode_tok_s") is not None:
                lines.append(f"  Decode tok/s: {summary['decode_tok_s']}")
            if "ctx" in summary:
                lines.append(f"  Ctx: {summary['ctx']}")
        lines.append("")
        lines.append("  Select action, Enter confirms")
        self.query_one("#detail-label", Label).update("\n".join(lines))
        actions = self.query_one("#install-action-table", DataTable)
        actions.clear(columns=True)
        actions.add_columns("Action", "Meaning")
        if not load_failed:
            actions.add_row("accept", "create launcher and metadata")
        actions.add_row("reject", "discard this result")
        actions.add_row("skip", "keep benchmark, decide later")
        actions.cursor_type = "row"
        actions.move_cursor(row=0, column=0)
        actions.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "install-action-table":
            return
        if self._load_failed:
            # no accept row; rows are: 0=reject, 1=skip
            if event.cursor_row == 0:
                self.action_reject()
            elif event.cursor_row == 1:
                self.action_skip()
        else:
            if event.cursor_row == 0:
                self.action_accept()
            elif event.cursor_row == 1:
                self.action_reject()
            elif event.cursor_row == 2:
                self.action_skip()

    def action_accept(self) -> None:
        if self._accepting:
            self.app.notify("Already accepting/deploying this model", severity="warning")
            return
        if not self.result or self.result["status"] != "benchmark_done":
            self.app.notify("No benchmark result to accept", severity="error")
            return

        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            self.app.notify("No remote host", severity="error")
            return

        benchmark_file = str(self.result["benchmark_file"])
        family = str(self.result.get("family", "?"))
        self._accepting = True
        self._set_busy(True, "Accepting and deploying")
        self.query_one("#detail-label", Label).update(
            "  Writing accepted metadata, deploying launcher, and refreshing remote state..."
        )
        actions = self.query_one("#install-action-table", DataTable)
        actions.clear(columns=True)
        actions.add_columns("Status")
        actions.add_row("accepting/deploying — please wait")

        from .commands import accept_model

        def _finish_accept(accept_result: dict[str, str]) -> None:
            self._accepting = False
            self._set_busy(False)
            if accept_result.get("status") == "ok":
                self.query_one("#status-label", Label).update(f"[green]Accepted: {family}[/green]")
                self.app.notify(f"Accepted: {family}")
                self.app.pop_screen()
            else:
                message = accept_result.get("message", "accept failed")
                self.query_one("#status-label", Label).update(
                    f"[red]Accept failed: {message}[/red]"
                )
                self.app.notify(f"Accept failed: {message}", severity="error")
                actions.clear(columns=True)
                actions.add_columns("Action", "Meaning")
                actions.add_row("accept", "retry create launcher and metadata")
                actions.add_row("reject", "discard this result")
                actions.add_row("skip", "keep benchmark, decide later")
                actions.cursor_type = "row"
                actions.move_cursor(row=0, column=0)
                actions.focus()

        def _run_accept() -> None:
            try:
                accept_result = accept_model(benchmark_file, host)
            except (RuntimeError, ValueError, OSError) as e:
                accept_result = {"status": "error", "message": str(e)}
            self.app.call_from_thread(_finish_accept, accept_result)

        self.run_worker(_run_accept, thread=True)

    def action_reject(self) -> None:
        if self._accepting:
            self.app.notify("Accept/deploy in progress", severity="warning")
            return
        family = self.result.get("family", "?") if self.result else "?"
        self.app.notify(f"Rejected: {family}")
        self.app.pop_screen()

    def action_skip(self) -> None:
        if self._accepting:
            self.app.notify("Accept/deploy in progress", severity="warning")
            return
        family = self.result.get("family", "?") if self.result else "?"
        self.app.notify(f"Skipped: {family}")
        self.app.pop_screen()

    def action_cancel(self) -> None:
        if self._accepting:
            self.app.notify("Cannot cancel while accept/deploy is in progress", severity="warning")
            return
        self.cancelled = True
        self._busy = False
        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if host:
            import threading

            def _remote_cancel() -> None:
                cancel_remote_processes(target)

            threading.Thread(target=_remote_cancel, daemon=True).start()
        self.app.notify("Cancelled install/download")
        self.app.pop_screen()


class BatchInstallScreen(Screen[None]):
    """Batch install multiple models sequentially."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, queue: list[dict[str, Any]]) -> None:
        super().__init__()
        self._queue = queue
        self._current = 0
        self._busy = False

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "Search", "Batch Install"])
        yield Label(f"[bold]Batch Install[/bold]  [dim]({len(self._queue)} models)[/dim]")
        yield Label("")
        yield Label("  Status:", id="batch-status")
        yield Label("", id="batch-detail")
        yield DataTable(id="batch-log")
        yield Footer()

    def on_mount(self) -> None:
        self._install_next()

    def _install_next(self) -> None:
        if self._current >= len(self._queue):
            self.query_one("#batch-status", Label).update("[green]All done[/green]")
            return
        candidate = self._queue[self._current]
        repo = candidate["repo"]
        status = self.query_one("#batch-status", Label)
        detail = self.query_one("#batch-detail", Label)
        status.update(f"[{self._current + 1}/{len(self._queue)}] Installing: {repo}")
        detail.update("Starting...")
        log = self.query_one("#batch-log", DataTable)
        log.clear(columns=True)
        log.add_columns("Step", "Message")
        log.add_row(str(self._current + 1), repo)

        # Push InstallProgressScreen for this model
        self.app.push_screen(InstallProgressScreen(self._current + 1, candidate))

    def action_cancel(self) -> None:
        self._queue.clear()
        self.app.pop_screen()


class DetailScreen(Screen[None]):
    """Screen showing model metadata and benchmark details."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, family: str, data: dict[str, Any]) -> None:
        super().__init__()
        self.family = family
        self.data = data

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "List", self.family])
        yield Label(f"[bold]Model Detail: {self.family}[/bold]")
        yield Label("")
        yield Label(f"  Repo:      {self.data.get('repo', '?')}")
        yield Label(f"  Alias:     {self.data.get('alias', '?')}")
        yield Label(f"  Quant:     {self.data.get('quant', '?')}")
        yield Label(f"  Profile:   {self.data.get('profile', '?')}")
        yield Label(f"  Launcher:  {self.data.get('launcher', '?')}")

        config = self.data.get("config", {})
        if config:
            yield Label(f"  Ctx:       {config.get('ctx', '?')}")

        profiles = self.data.get("profiles", {})
        if profiles:
            yield Label("")
            yield Label("  Profiles:")
            for name, info in profiles.items():
                if isinstance(info, dict):
                    yield Label(
                        f"    {name}: ctx={info.get('ctx', '?')}, flags={info.get('flags', '')}"
                    )
                else:
                    yield Label(f"    {name}")

        benchmark = self.data.get("benchmark", {})
        if benchmark:
            yield Label("")
            yield Label("  Benchmark:")
            for k, v in benchmark.items():
                yield Label(f"    {k}: {v}")

        yield Footer()


class EditModelScreen(Screen[None]):
    """Screen to edit all model config parameters."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, family: str, data: dict[str, Any]) -> None:
        super().__init__()
        self.family = family
        self.data = data

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "List", self.family, "Edit"])
        yield Label(f"[bold]Edit Model: {self.family}[/bold]  [dim]Enter or Ctrl+S saves[/dim]")
        with VerticalScroll():
            yield Label("  Profile:")
            yield Input(
                placeholder="speed / fastlong / balanced / reliable / tiny", id="profile-input"
            )
            yield Label("  Ctx (context size):")
            yield Input(placeholder="131072", id="ctx-input")
            yield Label("  Batch:")
            yield Input(placeholder="4096", id="batch-input")
            yield Label("  Ubatch:")
            yield Input(placeholder="256", id="ubatch-input")
            yield Label("  N-GPU layers (999 = all):")
            yield Input(placeholder="999", id="ngl-input")
            yield Label("  Cache type K:")
            yield Input(
                placeholder="f16 / q8_0 / q4_0 / q4_1 / iq4_nl / q5_0 / q5_1", id="cache-k-input"
            )
            yield Label("  Cache type V:")
            yield Input(
                placeholder="f16 / q8_0 / q4_0 / q4_1 / iq4_nl / q5_0 / q5_1", id="cache-v-input"
            )
            yield Label("  Ctx shift (on / off / integer):")
            yield Input(placeholder="on", id="ctx-shift-input")
            yield Label("  Reasoning (on / off):")
            yield Input(placeholder="on", id="reasoning-input")
            yield Label("  Backend:")
            yield Input(placeholder="vulkan / rocm", id="backend-input")
            yield Label("  Visible devices (blank = all, e.g. 0,1):")
            yield Input(placeholder="0,1", id="visible-devs-input")
            yield Label("  Split mode:")
            yield Input(placeholder="layer / row", id="split-mode-input")
            yield Label("  Tensor split:")
            yield Input(placeholder="1,1", id="tensor-split-input")
            yield Label("  Extra flags:")
            yield Input(placeholder="--no-mmap --mlock", id="flags-input")
        yield Footer()

    def on_mount(self) -> None:
        config = self.data.get("config") or {}

        def _set(id_: str, value: Any) -> None:
            self.query_one(f"#{id_}", Input).value = str(value) if value is not None else ""

        _set("profile-input", self.data.get("profile") or "")
        _set("ctx-input", config.get("ctx") or "")
        _set("batch-input", config.get("batch") or "")
        _set("ubatch-input", config.get("ubatch") or "")
        _set("ngl-input", config.get("ngl") or "")
        _set("cache-k-input", config.get("cache_type_k") or "")
        _set("cache-v-input", config.get("cache_type_v") or "")
        _set("ctx-shift-input", config.get("ctx_shift") or "")
        reasoning = config.get("reasoning")
        _set("reasoning-input", "off" if reasoning is False else "on")
        _set("backend-input", config.get("backend") or "")
        _set("visible-devs-input", config.get("visible_devices") or "")
        _set("split-mode-input", config.get("split_mode") or "")
        _set("tensor-split-input", config.get("tensor_split") or "")
        _set("flags-input", config.get("flags") or "")
        self.query_one("#profile-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def action_save(self) -> None:  # noqa: C901
        def _get(id_: str) -> str:
            return (self.query_one(f"#{id_}", Input).value or "").strip()

        profile = _get("profile-input")
        ctx_text = _get("ctx-input")
        batch_text = _get("batch-input")
        ubatch_text = _get("ubatch-input")
        ngl_text = _get("ngl-input")
        cache_k = _get("cache-k-input")
        cache_v = _get("cache-v-input")
        ctx_shift = _get("ctx-shift-input")
        reasoning_text = _get("reasoning-input")
        backend = _get("backend-input")
        visible_devs = _get("visible-devs-input")
        split_mode = _get("split-mode-input")
        tensor_split = _get("tensor-split-input")
        flags = _get("flags-input")

        if not profile:
            self.app.notify("Profile required", severity="error")
            return
        if profile not in ("speed", "fastlong", "balanced", "reliable", "tiny"):
            self.app.notify("Profile: speed/fastlong/balanced/reliable/tiny", severity="error")
            return
        if not ctx_text or not ctx_text.isdigit():
            self.app.notify("Ctx must be a positive integer", severity="error")
            return
        for name, val in (("batch", batch_text), ("ubatch", ubatch_text), ("ngl", ngl_text)):
            if val and not val.isdigit():
                self.app.notify(f"{name} must be integer if set", severity="error")
                return
        if backend and backend not in ("rocm", "vulkan"):
            self.app.notify("Backend: rocm, vulkan, or blank", severity="error")
            return
        if backend:
            if not split_mode:
                split_mode = "row" if backend == "rocm" else "layer"
            if not tensor_split:
                tensor_split = "1"
        if split_mode and split_mode not in ("layer", "row"):
            self.app.notify("Split mode: layer or row", severity="error")
            return
        if reasoning_text and reasoning_text not in ("on", "off"):
            self.app.notify("Reasoning: on or off", severity="error")
            return

        config: dict[str, Any] = {"ctx": int(ctx_text)}
        if batch_text:
            config["batch"] = int(batch_text)
        if ubatch_text:
            config["ubatch"] = int(ubatch_text)
        if ngl_text:
            config["ngl"] = int(ngl_text)
        if cache_k:
            config["cache_type_k"] = cache_k
        if cache_v:
            config["cache_type_v"] = cache_v
        if ctx_shift:
            config["ctx_shift"] = ctx_shift
        if reasoning_text:
            config["reasoning"] = reasoning_text == "on"
        if backend:
            config["backend"] = backend
        if visible_devs:
            config["visible_devices"] = visible_devs
        if split_mode:
            config["split_mode"] = split_mode
        if tensor_split:
            config["tensor_split"] = tensor_split
        if flags:
            config["flags"] = flags

        self.data["profile"] = profile
        self.data["config"] = config

        from .state import write_accepted

        write_accepted(self.family, self.data)

        from .service import update_launcher

        try:
            result = update_launcher(self.family)
            self.app.notify(f"Saved and regenerated launcher: {result.strip()}")
        except (RuntimeError, OSError) as e:
            self.app.notify(f"Saved metadata, launcher update failed: {e}", severity="warning")

        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


class ListScreen(Screen[None]):
    """Screen showing accepted and on-disk models."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("i", "hf_card", "HF Card"),
        Binding("space", "hf_card", "HF Card"),
        Binding("r", "quick_run", "Run"),
        Binding("d", "show_detail", "Detail"),
        Binding("e", "edit_model", "Edit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._accepted_repos: list[str] = []
        self._disk_repos: list[str] = []

    def _disk_models(self) -> list[tuple[str, str]]:
        return get_local_disk_models()

    def compose(self) -> ComposeResult:
        yield Label("[bold]Accepted Models[/bold]  (i/Space opens HF card)")
        yield Label("")
        yield DataTable(id="accepted-table")
        yield Label("")
        yield Label("[bold]On-Disk Models[/bold]")
        yield Label("")
        yield DataTable(id="disk-table")
        yield Footer()

    def on_mount(self) -> None:
        accepted_table = self.query_one("#accepted-table", DataTable)
        accepted_table.add_columns("Family", "Alias", "Repo", "Quant", "Profile", "Ctx")
        accepted_table.cursor_type = "row"
        accepted = list_accepted()
        self._accepted_repos = []
        for family, data in accepted:
            alias = data.get("alias", "?")
            repo = str(data.get("repo") or data.get("hf_repo") or "")
            quant = data.get("quant", "?")
            profile = data.get("profile", "?")
            ctx = data.get("config", {}).get("ctx", "?")
            self._accepted_repos.append(repo)
            accepted_table.add_row(family, alias, repo, quant, profile, ctx)
        if self._accepted_repos:
            accepted_table.move_cursor(row=0, column=0)
            accepted_table.focus()

        disk_table = self.query_one("#disk-table", DataTable)
        disk_table.add_columns("Repo", "Path")
        disk_table.cursor_type = "row"
        self._disk_repos = []
        for repo, path in self._disk_models():
            self._disk_repos.append(repo)
            disk_table.add_row(repo, path)

    def _selected_repo(self) -> str | None:
        focused = getattr(self.app, "focused", None)
        table_id = getattr(focused, "id", None)
        if table_id == "disk-table":
            table = self.query_one("#disk-table", DataTable)
            repos = self._disk_repos
        else:
            table = self.query_one("#accepted-table", DataTable)
            repos = self._accepted_repos
        cursor = table.cursor_row
        if cursor is None or cursor < 0 or cursor >= len(repos):
            return None
        repo = repos[cursor]
        return repo or None

    def action_hf_card(self) -> None:
        repo = self._selected_repo()
        if not repo:
            self.app.notify("No model repo selected", severity="warning")
            return
        self.app.push_screen(HFCardScreen(repo))

    def action_quick_run(self) -> None:
        repo = self._selected_repo()
        if not repo:
            self.app.notify("No model repo selected", severity="warning")
            return
        # Find accepted data for this repo
        accepted = list_accepted()
        for _family, data in accepted:
            if str(data.get("repo") or data.get("hf_repo")) == repo:
                self.app.push_screen(RunScreen())
                return
        self.app.notify("Model not in accepted list", severity="warning")

    def action_show_detail(self) -> None:
        repo = self._selected_repo()
        if not repo:
            self.app.notify("No model repo selected", severity="warning")
            return
        # Find accepted data for this repo
        accepted = list_accepted()
        for family, data in accepted:
            if str(data.get("repo") or data.get("hf_repo")) == repo:
                self.app.push_screen(DetailScreen(family, data))
                return
        self.app.notify("No metadata found for this repo", severity="warning")

    def action_edit_model(self) -> None:
        repo = self._selected_repo()
        if not repo:
            self.app.notify("No model repo selected", severity="warning")
            return
        # Find accepted data for this repo
        accepted = list_accepted()
        for family, data in accepted:
            if str(data.get("repo") or data.get("hf_repo")) == repo:
                self.app.push_screen(EditModelScreen(family, data))
                return
        self.app.notify("No metadata found for this repo", severity="warning")

    def action_back(self) -> None:
        self.app.pop_screen()


class DeleteScreen(Screen[None]):
    """Screen to delete a model repo."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("space", "toggle_selected", "Select"),
        Binding("d", "delete_selected", "Delete"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple[str, str]] = []
        self._selected: set[int] = set()

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "List", "Delete"])
        yield Container(
            Label("[bold]Delete Model[/bold]"),
            Label(""),
            Label("  Space selects rows, d deletes selected, Enter deletes highlighted"),
            Label(""),
            DataTable(id="delete-table"),
        )
        yield Footer()

    def _remote_cache_rows(self) -> dict[str, tuple[str, str]]:
        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            return {}
        return get_delete_list(host)

    def on_mount(self) -> None:
        self._load_delete_rows()
        self._render_delete_table()

    def _load_delete_rows(self) -> None:
        accepted = sorted(list_accepted(), key=lambda x: x[0])
        cache_rows = self._remote_cache_rows()
        self._rows = []
        self._row_display: list[tuple[str, str, str, str, str, str]] = []
        seen_repos: set[str] = set()
        for family, data in accepted:
            repo = data.get("repo") or data.get("hf_repo") or ""
            if not repo:
                continue
            alias = data.get("alias", "?")
            profile = data.get("profile", "?")
            disk, gguf = cache_rows.get(repo, ("-", "no"))
            self._rows.append((family, repo))
            self._row_display.append(("accepted", family, alias, profile, disk, gguf))
            seen_repos.add(repo)
        for repo, (disk, gguf) in sorted(cache_rows.items()):
            if repo in seen_repos:
                continue
            self._rows.append((repo, repo))
            self._row_display.append(("cache", repo, "-", "-", disk, gguf))

    def _render_delete_table(self) -> None:
        table = self.query_one("#delete-table", DataTable)
        cursor = table.cursor_row or 0
        table.clear(columns=True)
        table.add_columns(
            "Sel", "#", "Source", "Family/Repo", "Alias", "Profile", "Disk GB", "GGUF"
        )
        for idx, fields in enumerate(self._row_display):
            source, family, alias, profile, disk, gguf = fields
            mark = "✓" if idx in self._selected else ""
            table.add_row(mark, str(idx + 1), source, family, alias, profile, disk, gguf)
        if self._rows:
            table.cursor_type = "row"
            table.move_cursor(row=min(cursor, len(self._rows) - 1), column=0)
            table.focus()

    def _current_row(self) -> int | None:
        table = self.query_one("#delete-table", DataTable)
        cursor = table.cursor_row
        if cursor is None or cursor < 0 or cursor >= len(self._rows):
            return None
        return cursor

    def action_toggle_selected(self) -> None:
        cursor = self._current_row()
        if cursor is None:
            return
        if cursor in self._selected:
            self._selected.remove(cursor)
        else:
            self._selected.add(cursor)
        self._render_delete_table()

    def action_delete_selected(self) -> None:
        indices = sorted(self._selected)
        if not indices:
            cursor = self._current_row()
            if cursor is None:
                return
            indices = [cursor]
        self._delete_indices(indices)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "delete-table":
            return
        self.action_delete_selected()

    def _delete_indices(self, indices: list[int]) -> None:
        target = get_target()
        if not target:
            self.app.notify("Not initialized — run Init first", severity="error")
            return
        if not target.startswith("remote:"):
            self.app.notify("Delete requires remote target", severity="error")
            return
        failures = []
        deleted = 0
        for idx in indices:
            if idx < 0 or idx >= len(self._rows):
                continue
            family, repo = self._rows[idx]
            if not repo:
                failures.append(f"{family}: missing repo")
                continue
            try:
                result = delete_model(repo, target)
                if result == "ok":
                    deleted += 1
                else:
                    failures.append(f"{family}: {result}")
            except (RuntimeError, OSError) as e:
                failures.append(f"{family}: {e}")
        if failures:
            self.app.notify(
                f"Deleted {deleted}; failed {len(failures)}: {failures[0]}", severity="error"
            )
        else:
            self.app.notify(f"Deleted {deleted} model(s)")
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


class RunScreen(Screen[None]):
    """Screen to run a model server. Shows list with cursor navigation."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("p", "cycle_profile", "Profile"),
        Binding("o", "override", "Override"),
    ]

    PROFILES = PROFILES

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict[str, Any]] = []
        self._busy = False
        self._busy_text = ""
        self._spinner_idx = 0
        self._runtime_override_ctx: int | None = None
        self._runtime_override_profile: str | None = None

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "Run"])
        body: list[Any] = [Label("[bold]Run Model Server[/bold]"), Label("")]
        body.append(
            Label(
                "  Accepted models run with Enter. Disk-only rows show remote GGUFs not accepted yet."  # noqa: E501
            )
        )
        body.append(Label(""))
        body.append(DataTable(id="run-table"))
        body.append(Label("", id="run-status"))

        yield Container(*body)
        yield Footer()

    def _remote_disk_models(self) -> list[dict[str, str]]:
        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            return []
        return get_remote_disk_models(host)

    def _load_rows(self) -> None:
        self._rows = []
        accepted_by_repo: set[str] = set()
        accepted = sorted(list_accepted(), key=lambda x: x[0])
        for family, data in accepted:
            profiles_raw = data.get("profiles", {})
            if isinstance(profiles_raw, dict):
                profiles = [str(name) for name in profiles_raw.keys()]
            elif isinstance(profiles_raw, list):
                profiles = [str(name) for name in profiles_raw]
            else:
                profiles = []
            current = str(data.get("profile") or "balanced")
            if current not in profiles:
                profiles.insert(0, current)
            repo = str(data.get("repo") or data.get("hf_repo") or "")
            if repo:
                accepted_by_repo.add(repo)
            self._rows.append(
                {
                    "source": "accepted",
                    "family": family,
                    "alias": str(data.get("alias") or "?"),
                    "repo": repo,
                    "file": str(data.get("hf_file") or data.get("quant") or "?"),
                    "ctx": str((data.get("config") or {}).get("ctx") or "?"),
                    "profiles": profiles,
                    "profile_idx": profiles.index(current),
                    "disk_gb": "-",
                }
            )
        for disk in self._remote_disk_models():
            repo = disk.get("repo", "")
            if repo in accepted_by_repo:
                for row in self._rows:
                    if row.get("repo") == repo:
                        row["disk_gb"] = disk.get("disk_gb", "-")
                        break
                continue
            self._rows.append(
                {
                    "source": "disk-only",
                    "family": repo,
                    "alias": "not accepted",
                    "repo": repo,
                    "file": disk.get("file", "?"),
                    "ctx": "-",
                    "profiles": [],
                    "profile_idx": 0,
                    "disk_gb": disk.get("disk_gb", "-"),
                }
            )

    def _render_table(self) -> None:
        table = self.query_one("#run-table", DataTable)
        cursor = table.cursor_row or 0
        table.clear(columns=True)
        table.add_columns(
            "#", "Source", "Family/Repo", "Alias", "Profile", "Ctx", "Disk GB", "File"
        )
        table.cursor_type = "row"
        for i, row in enumerate(self._rows, 1):
            profiles = row.get("profiles") or []
            idx = int(row.get("profile_idx") or 0)
            profile = profiles[idx] if profiles else "-"
            table.add_row(
                str(i),
                str(row.get("source", "?")),
                str(row.get("family", "?")),
                str(row.get("alias", "?")),
                profile,
                str(row.get("ctx", "?")),
                str(row.get("disk_gb", "-")),
                str(row.get("file", "?")),
            )
        if self._rows:
            table.move_cursor(row=min(cursor, len(self._rows) - 1), column=0)

    def on_mount(self) -> None:
        self._load_rows()
        self._render_table()
        self.set_interval(0.2, self._tick_run_spinner)
        table = self.query_one("#run-table", DataTable)
        table.focus()

    def _set_run_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self._busy_text = text
        if not busy and text:
            self.query_one("#run-status", Label).update(text)

    def _tick_run_spinner(self) -> None:
        if not self._busy:
            return
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._spinner_idx = (self._spinner_idx + 1) % len(frames)
        self.query_one("#run-status", Label).update(
            f"[yellow]{frames[self._spinner_idx]} {self._busy_text}[/yellow]"
        )

    def _show_run_ok(self, family: str, profile: str, remote_host: str) -> None:
        self._set_run_busy(False, f"[green]✓ API up: {family} ({profile}) on {remote_host}[/green]")
        self.app.notify(f"API up: {family} ({profile})")
        self.set_timer(4.0, lambda: self.query_one("#run-status", Label).update(""))

    def action_cycle_profile(self) -> None:
        if not self._rows:
            return
        table = self.query_one("#run-table", DataTable)
        cursor = table.cursor_row
        if cursor is None:
            cursor = 0
        if cursor < 0 or cursor >= len(self._rows):
            return
        row = self._rows[cursor]
        profiles = row.get("profiles") or []
        if not profiles:
            self.app.notify("Disk-only row has no accepted profiles", severity="warning")
            return
        idx = (int(row.get("profile_idx") or 0) + 1) % len(profiles)
        row["profile_idx"] = idx
        self._render_table()
        table.move_cursor(row=cursor, column=0)

    def action_override(self) -> None:
        """Prompt for runtime ctx/profile override for this session."""
        from textual import on
        from textual.widgets import Input as TextInput

        class OverrideDialog(Screen[None]):
            BINDINGS = [
                Binding("escape", "cancel", "Cancel"),
                Binding("enter", "apply", "Apply"),
            ]

            def compose(self) -> ComposeResult:
                yield Label("[bold]Runtime Override[/bold]")
                yield Label("")
                yield Label("  Set temporary ctx/profile for this run only.")
                yield TextInput(placeholder="ctx (e.g. 32768)", id="ctx-input")
                yield TextInput(placeholder="profile (e.g. balanced)", id="profile-input")
                yield Footer()

            def on_mount(self) -> None:
                self.query_one("#ctx-input", TextInput).focus()

            @on(TextInput.Submitted)
            def on_submitted(self, event: TextInput.Submitted) -> None:
                self.action_apply()

            def action_apply(self) -> None:
                ctx = (self.query_one("#ctx-input", TextInput).value or "").strip()
                profile = (self.query_one("#profile-input", TextInput).value or "").strip()
                if not ctx and not profile:
                    self.app.notify("Enter at least one value", severity="warning")
                    return
                # Store override in parent RunScreen
                # Type: ignore screens access
                parent = self.app._screens[-2] if len(self.app._screens) > 1 else None  # type: ignore[attr-defined]
                if isinstance(parent, RunScreen):
                    parent._runtime_override_ctx = int(ctx) if ctx.isdigit() else None
                    parent._runtime_override_profile = profile or None
                    parent.app.notify(
                        f"Override set: ctx={parent._runtime_override_ctx}, profile={parent._runtime_override_profile}"  # noqa: E501
                    )
                self.app.pop_screen()

            def action_cancel(self) -> None:
                self.app.pop_screen()

        self.app.push_screen(OverrideDialog())

    def action_cursor_down(self) -> None:
        pass

    def action_cursor_up(self) -> None:
        pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "run-table":
            return
        cursor = event.cursor_row
        if cursor < 0 or cursor >= len(self._rows):
            self.app.notify("No models available", severity="warning")
            return
        row = self._rows[cursor]
        profiles = row.get("profiles") or []
        if not profiles or row.get("source") != "accepted":
            self.app.notify(
                "Disk-only model must be installed/accepted before running", severity="warning"
            )
            return
        profile = profiles[int(row.get("profile_idx") or 0)]
        self._start_server(str(row.get("family")), profile)

    def _start_server(self, family: str, profile: str) -> None:
        """Start the model server using oc-local."""
        # Apply runtime overrides if set
        effective_profile = self._runtime_override_profile or profile
        ctx_override = self._runtime_override_ctx

        oc_local = SCRIPT_DIR / "oc-local"
        if not oc_local.exists():
            self.app.notify("oc-local not found", severity="error")
            return

        target = get_target()
        if not target:
            self.app.notify("Not initialized — run Init first", severity="error")
            return
        if not target.startswith("remote:"):
            self.app.notify("Run requires remote target", severity="error")
            return
        remote_host = target.split(":", 1)[1].strip()
        if not remote_host:
            self.app.notify("Invalid remote target", severity="error")
            return

        status = self.query_one("#run-status", Label)
        override_note = f" (override ctx={ctx_override})" if ctx_override else ""
        status.update(
            f"[yellow]Starting {family} ({effective_profile}) on {remote_host}{override_note}...[/yellow]"  # noqa: E501
        )
        self._set_run_busy(
            True, f"Starting {family} ({effective_profile}) on {remote_host}{override_note}"
        )

        import threading

        def _run() -> None:
            try:
                ctx_str = str(self._runtime_override_ctx) if self._runtime_override_ctx else None
                status, message = start_server(
                    family, effective_profile, target, ctx_override=ctx_str
                )
                ok = status == "ok"
                if ok:
                    healthy = get_server_status(target) == "active"
                    if healthy:
                        self.app.call_from_thread(self._show_run_ok, family, profile, remote_host)
                    else:
                        self.app.call_from_thread(
                            self._set_run_busy,
                            False,
                            "[red]Started command returned, but API health check failed[/red]",
                        )
                        self.app.notify("API health check failed", severity="error")
                else:
                    self.app.call_from_thread(
                        self._set_run_busy,
                        False,
                        f"[red]oc-local failed: {message[:200]}[/red]",
                    )
                    self.app.notify(f"oc-local failed: {message[:200]}", severity="error")
            except (RuntimeError, ValueError, OSError) as e:
                err_msg = str(e)
                self.app.call_from_thread(self._set_run_busy, False, f"[red]Error: {err_msg}[/red]")
                self.app.notify(f"Error: {err_msg}", severity="error")

        threading.Thread(target=_run, daemon=True).start()

    def action_back(self) -> None:
        self.app.pop_screen()


class StatusScreen(Screen[None]):
    """Screen showing model-manager status."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("e", "edit_model", "Edit"),
        Binding("r", "restart_model", "Restart"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._target = ""
        self._running_family: str | None = None
        self._accepted: list[tuple[str, dict[str, Any]]] = []
        self._busy = False
        self._spinner_idx = 0

    def compose(self) -> ComposeResult:
        yield _breadcrumb_label(["Home", "Status"])
        yield Label("[bold]Status[/bold]")
        yield Label("")
        yield Label("", id="target-label")
        yield Label("  State:     ~/.local/share/local_llm/runs")
        yield Label("", id="running-label")
        yield Label("", id="accepted-label")
        yield Label("", id="default-label")
        yield Label("")
        yield Label("  Models:  [dim](e=edit, r=restart)[/dim]")
        yield DataTable(id="status-table")
        yield Label("")
        yield Label("  Active downloads:")
        yield DataTable(id="downloads-table")
        yield Label("", id="action-status")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick_spinner)
        self.call_after_refresh(self._load_status)

    def _load_status(self) -> None:
        config = read_config()
        self._target = config.get("target", "not set") if config else "not set"
        self._accepted = list_accepted()
        default_ok = has_default()
        running, running_ctx = detect_running_model(self._target)

        self._running_family = None
        if running.startswith("active: ") and "(not in accepted)" not in running:
            self._running_family = running.removeprefix("active: ")

        self.query_one("#target-label", Label).update(f"  Target:    [bold]{self._target}[/bold]")
        ctx_suffix = f" [dim](ctx {running_ctx:,})[/dim]" if running_ctx else ""
        running_markup = (
            f"[green]{running}[/green]{ctx_suffix}" if running.startswith("active") else running
        )
        self.query_one("#running-label", Label).update(f"  Running:   {running_markup}")
        self.query_one("#accepted-label", Label).update(f"  Accepted:  {len(self._accepted)}")
        self.query_one("#default-label", Label).update(
            f"  Default:   {'[green]yes[/green]' if default_ok else '[red]no[/red]'}"
        )
        self._populate_status_table()
        self._populate_downloads_table()

    def _tick_spinner(self) -> None:
        if not self._busy:
            return
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._spinner_idx = (self._spinner_idx + 1) % len(frames)
        try:
            self.query_one("#action-status", Label).update(
                f"[yellow]{frames[self._spinner_idx]} Restarting...[/yellow]"
            )
        except (LookupError, RuntimeError):
            pass

    def _set_action_status(self, text: str) -> None:
        try:
            self.query_one("#action-status", Label).update(text)
        except (LookupError, RuntimeError):
            pass

    def _populate_status_table(self) -> None:
        try:
            table = self.query_one("#status-table", DataTable)
        except (LookupError, RuntimeError):
            return
        table.clear(columns=True)
        table.add_columns("Family", "Alias", "Profile", "Ctx")
        table.cursor_type = "row"
        for family, data in self._accepted:
            alias = data.get("alias", "?")
            profile = data.get("profile", "?")
            ctx = str((data.get("config") or {}).get("ctx", "?"))
            mark = "[green]▶[/green] " if family == self._running_family else "  "
            table.add_row(mark + family, alias, profile, ctx)
        if self._accepted:
            running_idx = next(
                (i for i, (f, _) in enumerate(self._accepted) if f == self._running_family),
                0,
            )
            table.move_cursor(row=running_idx, column=0)
            table.focus()

    def _populate_downloads_table(self) -> None:
        table = self.query_one("#downloads-table", DataTable)
        table.clear(columns=True)
        table.add_columns("PID", "Repo", "File")
        host = self._target.split(":", 1)[1] if self._target.startswith("remote:") else None
        rows = get_remote_downloads(host) if host else []
        if not rows:
            table.add_row("-", "none", "")
            return
        for pid, repo, file_name in rows:
            table.add_row(pid, repo, file_name)

    def _selected_row(self) -> tuple[str, dict[str, Any]] | None:
        try:
            table = self.query_one("#status-table", DataTable)
            cursor = table.cursor_row
            if cursor is not None and 0 <= cursor < len(self._accepted):
                return self._accepted[cursor]
        except (LookupError, IndexError, RuntimeError):
            pass
        return None

    def action_edit_model(self) -> None:
        row = self._selected_row()
        if not row:
            self.app.notify("No model selected", severity="warning")
            return
        family, data = row
        self.app.push_screen(EditModelScreen(family, data))

    def action_restart_model(self) -> None:
        row = self._selected_row()
        if not row:
            self.app.notify("No model selected", severity="warning")
            return
        family, data = row
        if self._busy:
            self.app.notify("Restart already in progress", severity="warning")
            return

        profile = str(data.get("profile") or "balanced")
        target = self._target
        self._busy = True
        self._set_action_status("[yellow]Stopping...[/yellow]")

        import threading

        def _do_restart() -> None:
            try:
                stop_server(target)
                self.app.call_from_thread(self._set_action_status, "[yellow]Starting...[/yellow]")
                status, message = start_server(family, profile, target)
                if status == "ok":
                    healthy = get_server_status(target) == "active"
                    if healthy:
                        self.app.call_from_thread(
                            self._set_action_status,
                            f"[green]✓ Restarted: {family} ({profile})[/green]",
                        )
                        self.app.notify(f"Restarted: {family}")
                    else:
                        self.app.call_from_thread(
                            self._set_action_status,
                            "[red]Started but health check failed[/red]",
                        )
                        self.app.notify("Health check failed after restart", severity="error")
                else:
                    msg = message[:200]
                    self.app.call_from_thread(
                        self._set_action_status, f"[red]Restart failed: {msg}[/red]"
                    )
                    self.app.notify(f"Restart failed: {msg}", severity="error")
            except (RuntimeError, ValueError, OSError) as e:
                self.app.call_from_thread(self._set_action_status, f"[red]Error: {e}[/red]")
                self.app.notify(f"Restart error: {e}", severity="error")
            finally:
                self._busy = False

        threading.Thread(target=_do_restart, daemon=True).start()

    def action_back(self) -> None:
        self.app.pop_screen()


class CheckUpdatesScreen(Screen[None]):
    """Check for recommended model updates, apply if desired."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("backspace", "back", "Back"),
        Binding("enter", "apply", "Apply"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("[bold]Checking for Updates...[/bold]"),
            id="result",
        )
        yield Footer()

    def on_mount(self) -> None:
        import threading

        threading.Thread(target=self._do_check, daemon=True).start()

    def _do_check(self) -> None:
        from .service import check_updates

        try:
            result = check_updates(dry_run=True)
            self.app.call_from_thread(self._show_result, result)
        except Exception as e:
            self.app.call_from_thread(self._show_result, f"[red]Error: {e}[/red]")

    def _show_result(self, text: str) -> None:
        self.query_one("#result", Label).update(
            f"[bold]Updates Check[/bold]\n\n{text}\n\n[dim]enter = apply  ·  escape = back[/dim]"
        )

    def action_apply(self) -> None:
        import threading

        self.query_one("#result", Label).update("[bold]Applying Updates...[/bold]")
        threading.Thread(target=self._do_apply, daemon=True).start()

    def _do_apply(self) -> None:
        from .service import check_updates

        try:
            result = check_updates(dry_run=False)
            self.app.call_from_thread(self._show_result, result)
        except Exception as e:
            self.app.call_from_thread(self._show_result, f"[red]Error: {e}[/red]")

    def action_back(self) -> None:
        self.app.pop_screen()


class ModelManagerTUI(App[None]):
    """Main TUI application."""

    CSS = """
        #menu-container {
            align: center middle;
        }
        .title {
            color: $accent;
            text-align: center;
        }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def on_mount(self) -> None:
        self.push_screen(MainMenu())
