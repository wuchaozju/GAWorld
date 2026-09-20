"""Backwards-compatible shim for the legacy ``avatar_generator`` import path.

The canonical home for these symbols is now :mod:`gaworld.io.avatar`.
We alias this module to the canonical one via ``sys.modules`` so that
``import avatar_generator`` and ``from gaworld.io.avatar import ...``
return the *same* module object.

New code should import from ``gaworld.io.avatar`` directly.
"""

from __future__ import annotations

import sys

from gaworld.io import avatar as _avatar

sys.modules[__name__] = _avatar
