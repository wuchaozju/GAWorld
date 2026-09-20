"""Backwards-compatible shim for the legacy ``social_network`` import path.

The canonical home for these symbols is now :mod:`gaworld.social.network`.
We alias this module to the canonical one via ``sys.modules`` so that
``import social_network`` and ``from gaworld.social.network import ...``
return the *same* module object — preserving any writes to module-level
state used by tests or callers.

New code should import from ``gaworld.social.network`` directly.
"""

from __future__ import annotations

import sys

from gaworld.social import network as _network

sys.modules[__name__] = _network
