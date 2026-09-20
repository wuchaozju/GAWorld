"""Guard against silently-disabled extension hooks and builtin plugins.

Regression history: the economy hooks were once registered under the defunct
flat name 'economy_module', which raised ImportError at load time and
silently disabled the entire economy subsystem (tax, spending, shocks,
econ_security updates). Since K3f the economy rides the builtin plugin
surface instead of CONFIG["extensions"] — the guard's intent is unchanged:
every declared hook must resolve, and the economy must actually register
its lifecycle handlers.
"""

import importlib
import unittest

from gaworld.kernel import build_kernel
from gaworld.plugins import builtin_plugins
from gaworld.settings.integrations import integration_settings


class TestExtensionHooksResolve(unittest.TestCase):
    def test_all_registered_hooks_import(self):
        hooks = integration_settings()["extensions"]["hooks"]
        unresolved = []
        for event, paths in hooks.items():
            for path in paths:
                self.assertIn(":", path, f"{event}: '{path}' must be module:function")
                module_name, fn_name = path.split(":", 1)
                try:
                    module = importlib.import_module(module_name)
                except ImportError as exc:
                    unresolved.append(f"{path} ({exc})")
                    continue
                if not callable(getattr(module, fn_name, None)):
                    unresolved.append(f"{path} (not callable)")
        self.assertEqual(unresolved, [], f"unresolved hooks: {unresolved}")

    def test_economy_plugin_registers_lifecycle_handlers(self):
        plugins = {p.id: p for p in builtin_plugins()}
        self.assertIn("economy", plugins, "economy missing from builtin plugins")
        ctx = build_kernel({}, load_entry_points=False)
        plugins["economy"].setup(ctx)
        for event in (
            "on_simulation_start",
            "on_day_start",
            "on_agent_pre_step",
            "on_agent_post_step",
            "on_day_end",
            "on_simulation_end",
        ):
            self.assertTrue(
                ctx.bus._handlers.get(event),
                f"economy did not register a handler for {event}",
            )

    def test_all_builtin_plugins_set_up_cleanly(self):
        """A builtin plugin whose setup fails is silently deactivated by the
        registry — catch that here instead of in a broken simulation."""
        ctx = build_kernel({}, load_entry_points=False)
        for plugin in builtin_plugins():
            ctx.registry.register(plugin)
        active = ctx.registry.setup_all(ctx)
        expected = [p.id for p in builtin_plugins()]
        self.assertEqual(active, expected)


if __name__ == "__main__":
    unittest.main()
