"""Backwards-compatible shim for the legacy ``dynamic_behavior`` import path.

The canonical home for these symbols is now :mod:`gaworld.behavior.dynamic`.
``sys.modules`` aliasing makes both import paths return the *same* module
object — preserving module-level state and monkey-patching.

New code should import from ``gaworld.behavior.dynamic`` directly.
"""

from __future__ import annotations

import sys

from gaworld.behavior import dynamic as _dynamic

sys.modules[__name__] = _dynamic
