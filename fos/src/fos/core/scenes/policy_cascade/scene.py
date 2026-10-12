"""This file defines the policy cascade scene used by older simulations.

PolicyCascadeScene brings together the pieces that let agents pass policy
messages through hierarchy levels. Its deserialize function rebuilds a saved
policy cascade scene as the same kind of scene so it can be copied safely.
"""

from __future__ import annotations

from fos.core.scene import Scene

from .base import PolicyCascadeBaseMixin
from .distortion import PolicyCascadeDistortionMixin
from .followup import PolicyCascadeFollowUpMixin
from .messages import PolicyCascadeMessageMixin
from .prompts import PolicyCascadePromptMixin
from .runtime import PolicyCascadeRuntimeMixin
from .state import PolicyCascadeStateMixin
from .threads import PolicyCascadeThreadMixin


class PolicyCascadeScene(
    PolicyCascadeRuntimeMixin,
    PolicyCascadePromptMixin,
    PolicyCascadeMessageMixin,
    PolicyCascadeFollowUpMixin,
    PolicyCascadeThreadMixin,
    PolicyCascadeStateMixin,
    PolicyCascadeDistortionMixin,
    PolicyCascadeBaseMixin,
    Scene,
):
    """Strict top→mid→low cascade, single action per tier, downstream-only delivery."""

    TYPE = "policy_cascade_scene"

    @classmethod
    def deserialize(cls, data: dict) -> "PolicyCascadeScene":
        scene = cls.__new__(cls)
        scene.name = data.get("name", "")
        scene.initial_event = data.get("initial_event", "")
        scene.state = dict(data.get("state", {}))
        scene.tier_order = list(scene.state.get("tier_order", []))
        scene._tier_map = {}
        scene._agents_by_tier = {t: [] for t in scene.tier_order}
        return scene
