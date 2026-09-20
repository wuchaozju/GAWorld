"""Backwards-compatible shim for the legacy ``life_events`` import path.

The canonical home for these symbols is now :mod:`gaworld.events.life`.
``sys.modules`` aliasing makes both import paths return the *same*
module object — preserving module-level state and monkey-patching.

New code should import from ``gaworld.events.life`` directly.
"""

from __future__ import annotations

import sys

from gaworld.events import life as _life

sys.modules[__name__] = _life
