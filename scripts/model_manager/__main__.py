"""CLI entry point for model-manager Python backend."""

from __future__ import annotations

import argparse

from .commands import (
    cmd_delete,
    cmd_init,
    cmd_install,
    cmd_list,
    cmd_search,
    cmd_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="model-manager",
        description="Manage local LLM models — search, install, list, delete.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Set target and create state directories")
    p_init.add_argument("--target", required=True, help="local or remote:<host>")
    p_init.set_defaults(func=cmd_init)

    # search
    p_search = sub.add_parser(
        "search",
        help="Search and score models, save candidates for install",
    )
    p_search.add_argument("query", nargs="?", default="GGUF", help="search query")
    p_search.add_argument("--limit", type=int, default=30, help="max candidates to show")
    p_search.set_defaults(func=cmd_search)

    # install
    p_install = sub.add_parser(
        "install",
        help="Install a candidate by index (requires search first)",
    )
    p_install.add_argument(
        "--index",
        type=int,
        required=True,
        help="candidate index from search results (1-based)",
    )
    p_install.add_argument(
        "--profile",
        default="balanced",
        choices=["speed", "fastlong", "balanced", "reliable", "tiny"],
        help="profile for launcher",
    )
    p_install.add_argument("--ctx", default="32768", help="context size")
    p_install.set_defaults(func=cmd_install)

    # list
    p_list = sub.add_parser("list", help="List accepted models")
    p_list.set_defaults(func=cmd_list)

    # status
    p_status = sub.add_parser("status", help="Show model-manager status")
    p_status.set_defaults(func=cmd_status)

    # delete
    p_delete = sub.add_parser("delete", help="Delete an accepted model family")
    p_delete.add_argument("--family", required=True, help="family to delete")
    p_delete.set_defaults(func=cmd_delete)

    # tui
    sub.add_parser("tui", help="Launch interactive TUI")

    args = parser.parse_args()

    if args.command == "tui":
        from .tui import ModelManagerTUI

        ModelManagerTUI().run()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
