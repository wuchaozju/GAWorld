"""Backward-compatible entrypoint for the GAWorld dashboard server.

Older deployment scripts on the team server execute ``python3 dashboard_server.py``.
The implementation now lives in :mod:`gaworld.apps.dashboard_server`, so this
thin wrapper keeps those deployments working after the repository switches to
the packaged layout.
"""

from gaworld.apps.dashboard_server import run_server


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Serve the GAWorld dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
