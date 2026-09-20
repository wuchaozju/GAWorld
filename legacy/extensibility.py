"""Backwards-compatible shim for the legacy ``extensibility`` import path.

The canonical home for these symbols is now :mod:`gaworld.hooks`.
We alias this module to the canonical one via ``sys.modules`` so that
``import extensibility`` and ``from gaworld.hooks import ...``
return the *same* module object.

New code should import from ``gaworld.hooks`` directly.
"""

from __future__ import annotations

import sys

from gaworld import hooks as _hooks

sys.modules[__name__] = _hooks
