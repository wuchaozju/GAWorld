"""Backwards-compatible shim for the legacy ``llm_providers`` import path.

The canonical home for these symbols is now :mod:`gaworld.llm.providers`.
``sys.modules`` aliasing makes both import paths return the *same* module
object — preserving the module-level ``LLM_ROUTER`` singleton.

New code should import from ``gaworld.llm.providers`` directly.
"""

from __future__ import annotations

import sys

from gaworld.llm import providers as _providers

sys.modules[__name__] = _providers
