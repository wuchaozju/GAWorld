"""Dynamic-behavior engine package.

Hosts the migrated ``dynamic_behavior`` module — InterruptEngine,
SpontaneityEngine, need-based interrupts, inbox/social triggers,
SocialChainResolver, EnvironmentResponsePipeline with cascade chains,
and the ``evaluate_step_dynamics`` per-tick entry point.

For backwards compatibility the legacy ``dynamic_behavior`` import path
is preserved by a ``sys.modules`` alias shim at the project root, so
both ``import dynamic_behavior`` and ``from gaworld.behavior.dynamic
import ...`` return the same module object.

New code should import from ``gaworld.behavior.dynamic`` directly.
"""

from __future__ import annotations

__all__: list[str] = []
