"""Public sector: governments, their policies, and what they do to a run.

``policy`` holds the pure functions (a government's policies → the economy
config they produce, the transfers they pay, the brief residents read);
``plugin`` applies them to a running simulation. Off by default
(``CONFIG["public_sector"]["enabled"]``).
"""

from __future__ import annotations

__all__: list[str] = []
