"""Built-in plugin assembly.

This is the domain-side aggregation point the design doc calls
``gaworld.plugins.builtin`` — the ONE place that may import built-in plugin
classes. The kernel never imports domain logic; the simulator registers
these instances before ``registry.setup_all``.

Third-party plugins do not belong here: declare them in ``CONFIG["plugins"]``
or via the ``gaworld.plugins`` entry-point group instead.
"""

from __future__ import annotations


def validate_runtime_config(config):
    """Run built-in preflight checks outside warning-only plugin setup."""
    from gaworld.group.plugin import validate_config as validate_group_config
    from gaworld.organizations.validation import validate_config

    validate_config(config)
    validate_group_config(config)


def builtin_plugins():
    """Instantiate the built-in plugins (K3 migration adds one per stage)."""
    from gaworld.behavior.plugin import DynamicBehaviorPlugin
    from gaworld.cluster.plugin import ClusterSyncPlugin
    from gaworld.collaboration.plugin import CollaborationPlugin
    from gaworld.economy.plugin import EconomyPlugin
    from gaworld.events.plugin import LifeEventsPlugin
    from gaworld.family.plugin import FamilyPlugin
    from gaworld.goals_plugin import GoalsPlugin
    from gaworld.group.plugin import GroupPlugin
    from gaworld.infosources.plugin import InfoSourcesPlugin
    from gaworld.interests_plugin import InterestsPlugin
    from gaworld.moltbook.plugin import MoltbookPlugin
    from gaworld.multiplayer.plugin import MultiplayerPlugin
    from gaworld.organizations.plugin import OrganizationsPlugin
    from gaworld.personality.plugin import BigFivePlugin
    from gaworld.policy.plugin import InterventionPlugin
    from gaworld.skills.plugin import SkillsPlugin
    from gaworld.travel.plugin import TravelPlugin
    from gaworld.work.plugin import RealWorkPlugin
    from gaworld.world.home_plugin import HomeEnvironmentPlugin
    from gaworld.world.plugin import (
        LocalPhysicalPlugin,
        RoomsPlugin,
        SpatialPreferencesPlugin,
        TrafficPlugin,
        VehicleOwnershipPlugin,
        VenueCapacityPlugin,
    )

    return [
        # First: personality is a read-only prerequisite layer. Seeding it
        # before any other `agents.built` handler means a subsystem that later
        # wants to consult traits at build time can, without a reordering.
        BigFivePlugin(),
        # Media diets read Big Five openness, so they are built after traits
        # are seeded and before the simulator's own news bootstrap runs.
        InfoSourcesPlugin(),
        InterventionPlugin(),
        SkillsPlugin(),
        InterestsPlugin(),
        GoalsPlugin(),
        LifeEventsPlugin(),
        EconomyPlugin(),
        # Family sits after Economy so its day-end billing (priority -10)
        # lands on top of an already-settled day.
        FamilyPlugin(),
        # Travel reads the relationship obligation the social layer maintains
        # and bills fares through Economy, so it comes after both.
        TravelPlugin(),
        LocalPhysicalPlugin(),
        # Ownership is a precondition of mode choice, so it is assigned
        # whether or not the congestion layer is switched on.
        VehicleOwnershipPlugin(),
        # Traffic rides the same tick refresh as LocalPhysical and must commit
        # the previous tick's flows before any agent plans a trip this tick.
        TrafficPlugin(),
        # After LocalPhysical (same tick refresh); its move validator registers
        # at priority -10 so it runs after location_exists / venue_open.
        VenueCapacityPlugin(),
        # Inert unless `local_physical.rooms.enabled`: seats each resident in a
        # room after the move stage (the venue-capacity validator above may
        # already have picked the room for a trip).
        RoomsPlugin(),
        RealWorkPlugin(),
        DynamicBehaviorPlugin(),
        SpatialPreferencesPlugin(),
        # P5: per-agent home design + at-home perception. Comes after local-
        # physical so the at-home snippet layers on top of the crowd / open
        # snapshot when both fire.
        HomeEnvironmentPlugin(),
        CollaborationPlugin(),
        # After every other filter of `action.selected`, so a person playing a
        # resident has the last word on what that resident does.
        MultiplayerPlugin(),
        # A distributed world's tick sync: after the wait for players, so a
        # tick first waits for the people, then for the other machines.
        ClusterSyncPlugin(),
        # Last: it only observes (post_step buffer, day-end post) and must see
        # the step after every filter above has had its say.
        MoltbookPlugin(),
        # Inert unless `simulation_mode: "group"` (or `group.enabled` telemetry).
        # Its day-end handler carries its own priority, so position here only
        # orders its day-start cohort shift after the others' day start.
        GroupPlugin(),
        OrganizationsPlugin(),
    ]
