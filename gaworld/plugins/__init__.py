"""Built-in plugin assembly.

This is the domain-side aggregation point the design doc calls
``gaworld.plugins.builtin`` — the ONE place that may import built-in plugin
classes. The kernel never imports domain logic; the simulator registers
these instances before ``registry.setup_all``.

Third-party plugins do not belong here: declare them in ``CONFIG["plugins"]``
or via the ``gaworld.plugins`` entry-point group instead.
"""

from __future__ import annotations


def builtin_plugins():
    """Instantiate the built-in plugins (K3 migration adds one per stage)."""
    from gaworld.behavior.plugin import DynamicBehaviorPlugin
    from gaworld.collaboration.plugin import CollaborationPlugin
    from gaworld.economy.plugin import EconomyPlugin
    from gaworld.events.plugin import LifeEventsPlugin
    from gaworld.family.plugin import FamilyPlugin
    from gaworld.interests_plugin import InterestsPlugin
    from gaworld.personality.plugin import BigFivePlugin
    from gaworld.goals_plugin import GoalsPlugin
    from gaworld.policy.plugin import InterventionPlugin
    from gaworld.skills.plugin import SkillsPlugin
    from gaworld.work.plugin import RealWorkPlugin
    from gaworld.world.plugin import LocalPhysicalPlugin, SpatialPreferencesPlugin

    return [
        # First: personality is a read-only prerequisite layer. Seeding it
        # before any other `agents.built` handler means a subsystem that later
        # wants to consult traits at build time can, without a reordering.
        BigFivePlugin(),
        InterventionPlugin(),
        SkillsPlugin(),
        InterestsPlugin(),
        GoalsPlugin(),
        LifeEventsPlugin(),
        EconomyPlugin(),
        # Family sits after Economy so its day-end billing (priority -10)
        # lands on top of an already-settled day.
        FamilyPlugin(),
        LocalPhysicalPlugin(),
        RealWorkPlugin(),
        DynamicBehaviorPlugin(),
        SpatialPreferencesPlugin(),
        CollaborationPlugin(),
    ]
