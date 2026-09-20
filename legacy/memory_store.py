"""Backwards-compatible shim for the legacy ``memory_store`` import path.

The canonical home for these symbols is now :mod:`gaworld.memory.store`.
We alias this module to the canonical one via ``sys.modules`` so that
*both* of these keep working identically:

* ``import memory_store; memory_store.LOG_DIR = "..."``  — module-attribute
  mutation (used by tests).
* ``from memory_store import save_agent_memory`` — direct symbol import.

New code should import from ``gaworld.memory.store`` directly.
"""

from __future__ import annotations

import sys

from gaworld.memory import store as _store

# Replace this module in the import cache with the canonical one so that
# ``memory_store`` and ``gaworld.memory.store`` are the *same* module
# object — preserves writes to private state used by tests.
sys.modules[__name__] = _store
