"""CLI for installing/uninstalling/checking the morning-digest reminder
(docs/vision.md §2) — a plain OS-level notification, no agent involved.

Usage:
  uv run python -m engine.reminder.cli install [--time HH:MM] [--message TEXT]
  uv run python -m engine.reminder.cli uninstall
  uv run python -m engine.reminder.cli status
"""

from __future__ import annotations

import argparse

from engine.reminder.base import DEFAULT_MESSAGE, DEFAULT_TIME, select_backend


def main() -> None:
    parser = argparse.ArgumentParser(prog="engine.reminder.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="Install/update the Mon-Fri reminder")
    install_parser.add_argument("--time", default=DEFAULT_TIME, help="24h HH:MM local time (default: %(default)s)")
    install_parser.add_argument("--message", default=DEFAULT_MESSAGE)

    subparsers.add_parser("uninstall", help="Remove the reminder")
    subparsers.add_parser("status", help="Check whether the reminder is currently installed")

    args = parser.parse_args()
    backend = select_backend()

    if args.command == "install":
        backend.install(args.time, args.message)
        print(f"Reminder installed: {args.time} Mon-Fri.")
    elif args.command == "uninstall":
        backend.uninstall()
        print("Reminder uninstalled.")
    elif args.command == "status":
        result = backend.status()
        print(f"installed={result.installed}: {result.detail}")


if __name__ == "__main__":
    main()
