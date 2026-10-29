"""Backward-compatible entrypoint for the GAWorld dashboard server.

Older deployment scripts on the team server execute ``python3 dashboard_server.py``.
The implementation now lives in :mod:`gaworld.apps.dashboard_server`, so this
thin wrapper keeps those deployments working after the repository switches to
the packaged layout.
"""

from gaworld.apps.dashboard_cli import main
from gaworld.apps.dashboard_server import run_server  # noqa: F401 - existing import compatibility

if __name__ == "__main__":
    main()
