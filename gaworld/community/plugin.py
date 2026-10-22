"""Optional assembly entry point; publishing never changes simulation behavior."""

from gaworld.kernel import Plugin


class CommunityPlugin(Plugin):
    id = "community"

    def setup(self, ctx):
        # HTTP service uses this same facade; simulations need no community hooks.
        ctx.plugin_state(self.id)["service_class"] = "gaworld.community.store:CommunityStore"
