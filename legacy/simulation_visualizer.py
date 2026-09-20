"""Backwards-compatible shim for the legacy ``simulation_visualizer`` import path.

The canonical home for these symbols is now :mod:`gaworld.apps.visualizer`.
We alias this module to the canonical one via ``sys.modules`` so that
``import simulation_visualizer`` and ``from gaworld.apps.visualizer import ...``
return the *same* module object.

New code should import from ``gaworld.apps.visualizer`` directly.
"""

from __future__ import annotations

import sys

from gaworld.apps import visualizer as _visualizer

sys.modules[__name__] = _visualizer
