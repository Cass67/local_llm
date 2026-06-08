"""TUI entry point for model-manager using Textual."""

from __future__ import annotations

import json
import subprocess  # noqa: S404 # nosec: B404
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Markdown

from .state import (
    get_target,
    has_default,
    list_accepted,
    load_candidates,
    read_config,
    save_candidates,
    write_config,
)

SCRIPT_DIR = Path(__file__).resolve().parent.parent
MODEL_DISCOVERY = SCRIPT_DIR / "model-discovery.sh"


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
        Binding("space", "hf_card", "HF Card"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._searching = False
        self._spinner_idx = 0

    def compose(self) -> ComposeResult:
        yield Label("[bold]Search Models[/bold]")
        yield Label("")
        yield Label("  Enter search query (Enter installs result, i/Space opens HF card):")
        yield Input(placeholder="coding gguf", id="query-input")
        yield Label("", id="search-status")
        yield DataTable(id="results-table")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#query-input", Input).focus()
        table = self.query_one("#results-table", DataTable)
        table.add_columns("#", "Repo", "Score", "Quant")
        table.cursor_type = "row"
        self.set_interval(0.2, self._tick_spinner)

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

        host = target.split(":", 1)[1] if target.startswith("remote:") else None

        if host:
            cmd = [
                str(MODEL_DISCOVERY),
                "--host",
                host,
                "--query",
                query,
                "--limit",
                "30",
                "--json",
            ]
        else:
            cmd = [
                str(MODEL_DISCOVERY),
                "--local",
                "--query",
                query,
                "--limit",
                "30",
                "--json",
            ]

        def _finish_ok(ranked: list[dict[str, Any]]) -> None:
            self._searching = False
            save_candidates(ranked)
            table = self.query_one("#results-table", DataTable)
            table.clear(columns=True)
            table.add_columns("#", "Repo", "Score", "Quant")
            table.cursor_type = "row"
            for i, c in enumerate(ranked, 1):
                quant = c.get("best_quant", "?")
                table.add_row(str(i), c["repo"], str(c["score"]), quant)
            if ranked:
                table.move_cursor(row=0, column=0)
                table.focus()
            status.update(f"[green]Found {len(ranked)} candidates[/green]")
            self.app.notify(f"Saved {len(ranked)} candidates")

        def _finish_error(message: str) -> None:
            self._searching = False
            status.update(f"[red]{message}[/red]")
            self.app.notify(message, severity="error")

        def _run() -> None:
            try:
                result = subprocess.run(  # noqa: S603 # nosec: B603
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    self.app.call_from_thread(
                        _finish_error, f"Failed: {result.stderr.strip()[:100]}"
                    )
                    return

                scored = json.loads(result.stdout)
                ranked = scored.get("candidates", [])
                if not ranked:
                    self.app.call_from_thread(_finish_error, "No candidates found")
                    return
                self.app.call_from_thread(_finish_ok, ranked)
            except subprocess.TimeoutExpired:
                self.app.call_from_thread(_finish_error, "Search timed out")
            except Exception as e:
                self.app.call_from_thread(_finish_error, f"Error: {e}")

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
        script = r"""
import json, os, pathlib
roots=[pathlib.Path.home()/'.cache'/'huggingface'/'hub', pathlib.Path.home()/'.cache'/'local_llm'/'models', pathlib.Path.home()/'.cache'/'llama.cpp']
seen=set()
for root in roots:
    if not root.is_dir():
        continue
    for repo_dir in root.glob('models--*'):
        if not repo_dir.is_dir():
            continue
        repo=repo_dir.name.removeprefix('models--').replace('--','/',1)
        ggufs=sorted(repo_dir.rglob('*.gguf'))
        if not ggufs:
            key=(repo,'')
            if key in seen: continue
            seen.add(key)
            print(json.dumps({'kind':'cache-dir','repo':repo,'file':'','score':'no-gguf','quant':'missing'}))
            continue
        model_files=[p for p in ggufs if not p.name.lower().startswith('mmproj')]
        if not model_files:
            key=(repo,'')
            if key in seen: continue
            seen.add(key)
            print(json.dumps({'kind':'cache-dir','repo':repo,'file':'','score':'no-model-gguf','quant':'missing'}))
            continue
        # one row per repo: choose largest model GGUF, not mmproj
        path=max(model_files, key=lambda p: p.stat().st_size if p.exists() else 0)
        key=(repo,path.name)
        if key in seen: continue
        seen.add(key)
        print(json.dumps({'kind':'disk','repo':repo,'file':path.name,'score':'disk','quant':path.stem}))
"""
        rows: list[dict[str, str]] = []
        try:
            result = subprocess.run(  # noqa: S603 # nosec: B603
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "python3", "-"],
                input=script,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return rows
        if result.returncode != 0:
            return rows
        for line in result.stdout.splitlines():
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append({str(k): str(v) for k, v in parsed.items()})
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

    def compose(self) -> ComposeResult:
        yield Container(
            Label("[bold]Install Progress[/bold]"),
            Label(""),
            Label(f"  Candidate: [bold]{self.chosen['repo']}[/bold]"),
            Label(""),
            Label("  Status:", id="status-label"),
            Label("", id="detail-label"),
            DataTable(id="install-action-table"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick_install_spinner)
        self.run_worker(self._install_worker, thread=True)

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

    def _install_worker(self):
        """Worker that runs install and yields progress."""
        from .commands import (
            _download_on_host,
            _infer_alias,
            _infer_family,
            _read_benchmark_summary,
            _run_benchmark,
        )

        status = self.query_one("#status-label", Label)
        detail = self.query_one("#detail-label", Label)

        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            status.update("[red]Install requires remote target[/red]")
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
                with urllib.request.urlopen(
                    f"https://huggingface.co/api/models/{encoded}/tree/main", timeout=20
                ) as response:
                    tree = json.load(response)
                siblings = []
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
                vram_result = subprocess.run(  # noqa: S603 # nosec: B603
                    [
                        "ssh",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "ConnectTimeout=5",
                        host,
                        'total=0; for f in /sys/class/drm/card*/device/mem_info_vram_total; do [ -r "$f" ] && total=$((total + $(cat "$f"))); done; [ "$total" -gt 0 ] && echo "$total"',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                try:
                    vram_gb = int(vram_result.stdout.strip()) / 1073741824
                except ValueError:
                    vram_gb = 20.0
                payload = [{"id": repo, "tags": ["gguf"], "siblings": siblings}]
                ranked = subprocess.check_output(
                    [
                        "python3",
                        str(SCRIPT_DIR / "model-fit.py"),
                        "--hardware-json",
                        json.dumps({"source": f"remote:{host}", "vram_gb": vram_gb}),
                        "--limit",
                        "1",
                        "--json",
                    ],
                    input=json.dumps(payload),
                    text=True,
                    timeout=30,
                )
                candidate = json.loads(ranked)["candidates"][0]
                hf_file = candidate.get("best_file", "")
                quant = candidate.get("best_quant", "unknown") or "unknown"
            except Exception as e:
                status.update("[red]No GGUF file found[/red]")
                detail.update(f"  Could not resolve GGUF: {e}")
                self.app.notify("No GGUF file found for cached repo", severity="error")
                self.app.call_from_thread(self._set_busy, False)
                return
        if not hf_file:
            status.update("[red]No GGUF file found[/red]")
            detail.update("  HF repo has no GGUF file to download.")
            self.app.notify("No GGUF file found for cached repo", severity="error")
            self.app.call_from_thread(self._set_busy, False)
            return
        profile = "balanced"
        ctx = "131072"
        family = _infer_family(repo)
        alias = _infer_alias(repo)

        self.app.call_from_thread(self._set_busy, True, "Downloading")
        self.app.call_from_thread(detail.update, f"  Repo: {repo}")

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
                    size_result = subprocess.run(  # noqa: S603 # nosec: B603
                        [
                            "ssh",
                            "-o",
                            "BatchMode=yes",
                            "-o",
                            "ConnectTimeout=5",
                            host,
                            "du",
                            "-sb",
                            f"~/.cache/huggingface/hub/{repo_dir}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    size_text = size_result.stdout.split()[0] if size_result.stdout.split() else "0"
                    size_bytes = int(size_text)
                except Exception:
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
        except Exception as e:
            result = {"status": "error", "message": str(e)}
        finally:
            stop_monitor.set()

        if self.cancelled:
            self.app.call_from_thread(self._set_busy, False)
            return

        if result["status"] == "error":
            self.app.call_from_thread(self._set_busy, False)
            status.update(f"[red]Failed: {result['message']}[/red]")
            self.app.notify(f"Install failed: {result['message']}", severity="error")
            self.app.call_later(self.app.pop_screen)
            return

        if result["status"] == "benchmark_done":
            self.app.call_from_thread(self._set_busy, False)
            self.result = result
            summary = cast(dict, result.get("benchmark_summary", {}))
            status.update("[green]Benchmark complete[/green]")
            lines = [f"  Family: {result.get('family', '?')}"]
            if "load_status" in summary:
                lines.append(f"  Load: {summary['load_status']}")
            if summary.get("prompt_tok_s") is not None:
                lines.append(f"  Prompt tok/s: {summary['prompt_tok_s']}")
            if summary.get("decode_tok_s") is not None:
                lines.append(f"  Decode tok/s: {summary['decode_tok_s']}")
            if "ctx" in summary:
                lines.append(f"  Ctx: {summary['ctx']}")
            lines.append("")
            lines.append("  Select action, Enter confirms")
            detail.update("\n".join(lines))
            actions = self.query_one("#install-action-table", DataTable)
            actions.clear(columns=True)
            actions.add_columns("Action", "Meaning")
            actions.add_row("accept", "create launcher and metadata")
            actions.add_row("reject", "discard this result")
            actions.add_row("skip", "keep benchmark, decide later")
            actions.cursor_type = "row"
            actions.move_cursor(row=0, column=0)
            actions.focus()
            return

        status.update(f"[yellow]{result.get('message', 'Unknown')}[/yellow]")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "install-action-table":
            return
        if event.cursor_row == 0:
            self.action_accept()
        elif event.cursor_row == 1:
            self.action_reject()
        elif event.cursor_row == 2:
            self.action_skip()

    def action_accept(self) -> None:
        if not self.result or self.result["status"] != "benchmark_done":
            self.app.notify("No benchmark result to accept", severity="error")
            return

        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            self.app.notify("No remote host", severity="error")
            return

        status = self.query_one("#status-label", Label)
        status.update("[yellow]Accepting...[/yellow]")

        from .commands import accept_model

        try:
            accept_result = accept_model(self.result["benchmark_file"], host)
        except Exception as e:
            accept_result = {"status": "error", "message": str(e)}

        if accept_result["status"] == "ok":
            self.app.notify(f"Accepted: {self.result.get('family', '?')}")
        else:
            self.app.notify(f"Accept failed: {accept_result['message']}", severity="error")
        self.app.pop_screen()

    def action_reject(self) -> None:
        family = self.result.get("family", "?") if self.result else "?"
        self.app.notify(f"Rejected: {family}")
        self.app.pop_screen()

    def action_skip(self) -> None:
        family = self.result.get("family", "?") if self.result else "?"
        self.app.notify(f"Skipped: {family}")
        self.app.pop_screen()

    def action_cancel(self) -> None:
        self.cancelled = True
        self._busy = False
        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        repo = self.chosen.get("repo", "")
        if host:
            import threading

            def _remote_cancel() -> None:
                subprocess.run(  # noqa: S603 # nosec: B603
                    [
                        "ssh",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "ConnectTimeout=5",
                        host,
                        "bash",
                        "-lc",
                        "pkill -f '[h]f download' || true; "
                        "pkill -f '[h]uggingface.*download' || true; "
                        "pkill -f '[f]ile_download' || true; "
                        "systemctl --user stop llama-server.service >/dev/null 2>&1 || true; "
                        "pkill -u \"$(id -u)\" -f '[l]lama-server' >/dev/null 2>&1 || true",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )

            threading.Thread(target=_remote_cancel, daemon=True).start()
        self.app.notify("Cancelled install/download")
        self.app.pop_screen()


class ListScreen(Screen[None]):
    """Screen showing accepted and on-disk models."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def _disk_models(self) -> list[tuple[str, str]]:
        roots = [
            Path.home() / ".cache" / "huggingface" / "hub",
            Path.home() / ".cache" / "local_llm" / "models",
            Path.home() / ".cache" / "llama.cpp",
        ]
        rows: dict[str, str] = {}
        for root in roots:
            if not root.is_dir():
                continue
            for repo_dir in root.glob("models--*"):
                if not repo_dir.is_dir():
                    continue
                repo = repo_dir.name.removeprefix("models--").replace("--", "/", 1)
                ggufs = sorted(repo_dir.rglob("*.gguf"))
                rows[repo] = str(ggufs[0]) if ggufs else str(repo_dir)
        return sorted(rows.items())

    def compose(self) -> ComposeResult:
        yield Label("[bold]Accepted Models[/bold]")
        yield Label("")
        yield DataTable(id="accepted-table")
        yield Label("")
        yield Label("[bold]On-Disk Models[/bold]")
        yield Label("")
        yield DataTable(id="disk-table")
        yield Footer()

    def on_mount(self) -> None:
        accepted_table = self.query_one("#accepted-table", DataTable)
        accepted_table.add_columns("Family", "Alias", "Quant", "Profile", "Ctx")
        accepted = list_accepted()
        for family, data in accepted:
            alias = data.get("alias", "?")
            quant = data.get("quant", "?")
            profile = data.get("profile", "?")
            ctx = data.get("config", {}).get("ctx", "?")
            accepted_table.add_row(family, alias, quant, profile, ctx)

        disk_table = self.query_one("#disk-table", DataTable)
        disk_table.add_columns("Repo", "Path")
        for repo, path in self._disk_models():
            disk_table.add_row(repo, path)

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
        script = r"""
import json, pathlib, subprocess
roots=[pathlib.Path.home()/'.cache'/'huggingface'/'hub', pathlib.Path.home()/'.cache'/'local_llm'/'models', pathlib.Path.home()/'.cache'/'llama.cpp']
for root in roots:
    if not root.is_dir():
        continue
    for repo_dir in root.glob('models--*'):
        if not repo_dir.is_dir():
            continue
        repo=repo_dir.name.removeprefix('models--').replace('--','/',1)
        try:
            size=int(subprocess.check_output(['du','-sb',str(repo_dir)], text=True).split()[0])
        except Exception:
            size=0
        gguf='yes' if any(p.name.lower().endswith('.gguf') and not p.name.lower().startswith('mmproj') for p in repo_dir.rglob('*.gguf')) else 'no'
        print(json.dumps({'repo': repo, 'size_gb': f'{size/1_000_000_000:.1f}' if size else '-', 'gguf': gguf}))
"""
        try:
            result = subprocess.run(  # noqa: S603 # nosec: B603
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "python3", "-"],
                input=script,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return {}
        rows: dict[str, tuple[str, str]] = {}
        for line in result.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("repo"):
                rows[str(item["repo"])] = (
                    str(item.get("size_gb") or "-"),
                    str(item.get("gguf") or "no"),
                )
        return rows

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
                result = subprocess.run(  # noqa: S603 # nosec: B603
                    [
                        "bash",
                        str(SCRIPT_DIR / "model-manager.sh"),
                        "delete",
                        repo,
                        "--target",
                        target,
                        "--yes",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    deleted += 1
                else:
                    failures.append(f"{family}: {result.stderr.strip()[:120] or 'delete failed'}")
            except Exception as e:
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
    ]

    PROFILES = ("speed", "fastlong", "balanced", "reliable", "tiny")

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict[str, Any]] = []
        self._busy = False
        self._busy_text = ""
        self._spinner_idx = 0

    def compose(self) -> ComposeResult:
        body: list[Any] = [Label("[bold]Run Model Server[/bold]"), Label("")]
        body.append(
            Label("  Accepted models run with Enter. Disk-only rows show remote GGUFs not accepted yet.")
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
        script = r"""
import json, pathlib
root=pathlib.Path.home()/'.cache'/'huggingface'/'hub'
for repo_dir in sorted(root.glob('models--*')):
    if not repo_dir.is_dir():
        continue
    repo=repo_dir.name.removeprefix('models--').replace('--','/')
    ggufs=[]
    for p in repo_dir.rglob('*.gguf'):
        if p.name.lower().startswith('mmproj'):
            continue
        try:
            size=p.stat().st_size
        except OSError:
            size=0
        ggufs.append((size,p.name))
    if not ggufs:
        continue
    ggufs.sort(reverse=True)
    size,name=ggufs[0]
    print(json.dumps({
        'repo': repo,
        'file': name,
        'disk_gb': f'{sum(s for s, _ in ggufs)/1_000_000_000:.1f}',
    }))
"""
        try:
            result = subprocess.run(  # noqa: S603 # nosec: B603
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "python3", "-"],
                input=script,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        rows = []
        for line in result.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append({str(k): str(v) for k, v in item.items()})
        return rows

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
            self.app.notify("Disk-only model must be installed/accepted before running", severity="warning")
            return
        profile = profiles[int(row.get("profile_idx") or 0)]
        self._start_server(str(row.get("family")), profile)

    def _start_server(self, family: str, profile: str) -> None:
        """Start the model server using oc-local."""
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
        status.update(f"[yellow]Starting {family} ({profile}) on {remote_host}...[/yellow]")
        self._set_run_busy(True, f"Starting {family} ({profile}) on {remote_host}")

        import threading

        def _run() -> None:
            try:
                result = subprocess.run(  # noqa: S603 # nosec: B603
                    ["bash", str(oc_local), family, profile, "--remote", remote_host],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if result.returncode == 0:
                    health = subprocess.run(  # noqa: S603 # nosec: B603
                        [
                            "ssh",
                            "-o",
                            "BatchMode=yes",
                            "-o",
                            "ConnectTimeout=5",
                            remote_host,
                            "curl",
                            "-fsS",
                            "--max-time",
                            "5",
                            "http://127.0.0.1:8080/v1/models",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if health.returncode == 0:
                        self.app.call_from_thread(self._show_run_ok, family, profile, remote_host)
                    else:
                        self.app.call_from_thread(
                            self._set_run_busy,
                            False,
                            "[red]Started command returned, but API health check failed[/red]",
                        )
                        self.app.call_later(
                            lambda: self.app.notify("API health check failed", severity="error")
                        )
                else:
                    self.app.call_from_thread(
                        self._set_run_busy,
                        False,
                        f"[red]oc-local failed: {result.stderr.strip()[:200]}[/red]",
                    )
                    self.app.call_later(
                        lambda: self.app.notify(
                            f"oc-local failed: {result.stderr.strip()[:200]}",
                            severity="error",
                        )
                    )
            except Exception as e:
                err_msg = str(e)
                self.app.call_from_thread(self._set_run_busy, False, f"[red]Error: {err_msg}[/red]")
                self.app.call_later(lambda: self.app.notify(f"Error: {err_msg}", severity="error"))

        threading.Thread(target=_run, daemon=True).start()

    def action_back(self) -> None:
        self.app.pop_screen()


class StatusScreen(Screen[None]):
    """Screen showing model-manager status."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        config = read_config()
        target = config.get("target", "?") if config else "not set"
        accepted = list_accepted()
        default_ok = has_default()

        yield Label("[bold]Status[/bold]")
        yield Label("")
        yield Label(f"  Target:    [bold]{target}[/bold]")
        yield Label("  State:     ~/.local/share/local_llm/runs")
        yield Label(f"  Accepted:  {len(accepted)}")
        yield Label(f"  Default:   {'[green]yes[/green]' if default_ok else '[red]no[/red]'}")
        yield Label("")

        if accepted:
            yield Label("  Models:")
            yield DataTable(id="status-table")

        yield Label("")
        yield Label("  Active downloads:")
        yield DataTable(id="downloads-table")

        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._populate_status_table)
        self.call_after_refresh(self._populate_downloads_table)

    def _populate_status_table(self) -> None:
        try:
            table = self.query_one("#status-table", DataTable)
        except Exception:
            return
        table.add_columns("Family", "Alias")
        accepted = list_accepted()
        for family, data in accepted:
            alias = data.get("alias", "?")
            table.add_row(family, alias)

    def _remote_downloads(self) -> list[tuple[str, str, str]]:
        target = get_target() or ""
        host = target.split(":", 1)[1] if target.startswith("remote:") else None
        if not host:
            return []
        try:
            result = subprocess.run(  # noqa: S603 # nosec: B603
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=5",
                    host,
                    "pgrep",
                    "-af",
                    "[h]f download|[h]uggingface.*download|[f]ile_download",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return []
        rows = []
        for line in result.stdout.splitlines():
            parts = line.split()
            pid = parts[0] if parts else "?"
            repo = "?"
            file_name = ""
            if "download" in parts:
                idx = parts.index("download")
                if idx + 1 < len(parts):
                    repo = parts[idx + 1]
            if "--include" in parts:
                idx = parts.index("--include")
                if idx + 1 < len(parts):
                    file_name = parts[idx + 1]
            rows.append((pid, repo, file_name))
        return rows

    def _populate_downloads_table(self) -> None:
        table = self.query_one("#downloads-table", DataTable)
        table.add_columns("PID", "Repo", "File")
        rows = self._remote_downloads()
        if not rows:
            table.add_row("-", "none", "")
            return
        for pid, repo, file_name in rows:
            table.add_row(pid, repo, file_name)

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
