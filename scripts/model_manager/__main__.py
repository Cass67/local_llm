"""CLI entry point for model-manager Python backend."""

from __future__ import annotations

import argparse

from .commands import cmd_delete, cmd_init, cmd_install, cmd_list, cmd_status


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="model-manager",
        description="Manage local LLM models — discover, install, list, delete.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Set target and create state directories")
    p_init.add_argument("--target", required=True, help="local or remote:<host>")
    p_init.set_defaults(func=cmd_init)

    # install
    p_install = sub.add_parser(
        "install",
        help="Discover, score, and accept a model in one step",
    )
    p_install.add_argument("query", nargs="?", default="GGUF", help="search query")
    p_install.add_argument("--family", help="model family name (inferred if omitted)")
    p_install.add_argument(
        "--profile",
        default="balanced",
        choices=["speed", "fastlong", "balanced", "reliable", "tiny"],
        help="profile for launcher",
    )
    p_install.add_argument("--limit", type=int, default=5, help="max candidates to consider")
    p_install.add_argument("--ctx", default="32768", help="context size for accepted metadata")
    p_install.add_argument(
        "--full", action="store_true", help="run full benchmark (not yet implemented)"
    )
    p_install.add_argument(
        "--hardware-json", default="{}", help="hardware facts as JSON for scoring"
    )
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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
