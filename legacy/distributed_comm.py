"""Backwards-compatible shim for the legacy ``distributed_comm`` import path.

The canonical home for these symbols is now :mod:`gaworld.distributed.comm`.
``sys.modules`` aliasing makes both import paths return the *same*
module object — preserving module-level state and monkey-patching.

New code should import from ``gaworld.distributed.comm`` directly.
"""

from __future__ import annotations

import sys

from gaworld.distributed import comm as _comm

sys.modules[__name__] = _comm
