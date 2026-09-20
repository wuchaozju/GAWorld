"""Backwards-compatible shim for the legacy ``environment`` import path.

The canonical home for these symbols is now :mod:`gaworld.env.system`.
We alias this module to the canonical one via ``sys.modules`` so that
``import environment`` and ``from gaworld.env.system import ...`` return
the *same* module object — preserving any writes to module-level state.

New code should import from ``gaworld.env.system`` directly.
"""

from __future__ import annotations

import sys

from gaworld.env import system as _system

sys.modules[__name__] = _system
