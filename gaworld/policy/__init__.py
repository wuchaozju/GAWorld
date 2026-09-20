"""Platform-intervention metrics package.

Hosts the migrated ``intervention_policy`` module — PolicySim-inspired
recommendation / exposure intervention metrics, stance tracking, and
risk-score helpers.

For backwards compatibility the legacy ``intervention_policy`` import
path is preserved by a ``sys.modules`` alias shim at the project root,
so both ``import intervention_policy`` and
``from gaworld.policy.intervention import ...`` return the same module
object.

New code should import from ``gaworld.policy.intervention`` directly.
"""

from __future__ import annotations

__all__: list[str] = []
