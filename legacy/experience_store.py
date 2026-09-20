"""Backwards-compatible shim for the legacy ``experience_store`` import path.

The canonical home for these symbols is now :mod:`gaworld.memory.experience`.
We alias this module to the canonical one via ``sys.modules`` so that
``import experience_store`` and ``from gaworld.memory.experience import ...``
return the *same* module object — preserving any writes to module-level state.

New code should import from ``gaworld.memory.experience`` directly.
"""

from __future__ import annotations

import sys

from gaworld.memory import experience as _experience

sys.modules[__name__] = _experience
