"""Backwards-compatible shim for the legacy ``intervention_policy`` import path.

The canonical home for these symbols is now :mod:`gaworld.policy.intervention`.
``sys.modules`` aliasing makes both import paths return the *same* module
object — preserving module-level state and monkey-patching.

New code should import from ``gaworld.policy.intervention`` directly.
"""

from __future__ import annotations

import sys

from gaworld.policy import intervention as _intervention

sys.modules[__name__] = _intervention
