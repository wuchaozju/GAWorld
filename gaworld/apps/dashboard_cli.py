"""Shared startup arguments for all supported dashboard entry points."""

from __future__ import annotations

import argparse


def boolean(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("use True or False")


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8766, help="Bind port")
    parser.add_argument(
        "--multi-user",
        "--multi_user",
        type=boolean,
        nargs="?",
        const=True,
        default=False,
        help="Enable account login and isolated user workspaces (True/False; default: False)",
    )


def main(argv: list[str] | None = None) -> None:
    from gaworld import accounts
    from gaworld.apps import dashboard_server

    parser = argparse.ArgumentParser(description="Serve the GAWorld dashboard")
    configure_parser(parser)
    args = parser.parse_args(argv)
    try:
        dashboard_server.run_server(host=args.host, port=args.port, multi_user=args.multi_user)
    except accounts.AccountConfigurationError as exc:
        parser.exit(
            2,
            f"Multi-user startup failed: {exc}. Initialize accounts with python -m gaworld.accounts init --admin <name>.\n",
        )
