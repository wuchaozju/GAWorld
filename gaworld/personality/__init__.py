"""Big Five (OCEAN) personality.

``traits`` and ``anchors`` are stdlib-only leaves; ``plugin`` is the only
module that touches CONFIG, the filesystem or the kernel. Consumers import the
three functions below and nothing else — no module outside this package should
index ``agent["ext"]["big_five"]`` directly.
"""

from gaworld.personality.anchors import anchor_block, personality_line
from gaworld.personality.traits import style_fit, trait_modifier, traits_of

__all__ = [
    "anchor_block",
    "personality_line",
    "style_fit",
    "trait_modifier",
    "traits_of",
]
