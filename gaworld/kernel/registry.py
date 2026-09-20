"""Plugin base class and registry.

Plugins are the unit of pluggability: a plugin owns its config namespace
(``ctx.config[plugin.id]``), its per-agent state (``ctx.agent_ext(agent, id)``),
and its on-disk outputs (``output/<id>/`` — Database-per-Plugin). ``setup``
is where a plugin registers bus hooks, controller validators, cognition
stages, or actions; the kernel never imports domain modules directly.

Assembly sources, merged in order:

1. built-in plugin classes passed by the simulator,
2. ``CONFIG["plugins"]`` entries: ``{"class": "pkg.mod:Class", "enabled": true}``,
3. ``gaworld.plugins`` entry points (``pip install`` third-party plugins;
   loaded without an allowlist by project decision — failures only warn).
"""

from __future__ import annotations

import importlib
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from gaworld.logging_setup import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from gaworld.kernel.context import SimContext

_LOG = get_logger("gaworld.kernel.registry")

ENTRY_POINT_GROUP = "gaworld.plugins"


class Plugin:
    """Base class for GAWorld plugins.

    Subclasses must set ``id`` (unique; doubles as the config, storage and
    ``agent_ext`` namespace) and may set ``requires`` to declare dependencies
    on other plugin ids (setup runs in dependency order).
    """

    id: str = ""
    requires: tuple[str, ...] = ()

    def setup(self, ctx: "SimContext") -> None:  # pragma: no cover - interface
        """Register hooks / validators / stages / actions. Called once."""

    def teardown(self, ctx: "SimContext") -> None:  # pragma: no cover - interface
        """Release resources. Called once at simulation end, reverse order."""

    def output_dir(self, ctx: "SimContext") -> Path:
        """This plugin's owned output namespace (Database-per-Plugin)."""
        base = Path(ctx.config.get("output_root", "output"))
        return base / self.id


class PluginRegistry:
    """Collects, orders and drives plugin lifecycles."""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._setup_order: list[str] = []

    # -- assembly ----------------------------------------------------------

    def register(self, plugin: Plugin) -> bool:
        pid = getattr(plugin, "id", "")
        if not pid or not isinstance(pid, str):
            _LOG.warning("plugin %r has no valid `id`; skipped", plugin)
            return False
        if pid in self._plugins:
            _LOG.warning("plugin id `%s` already registered; skipped duplicate", pid)
            return False
        self._plugins[pid] = plugin
        return True

    def load_config_plugins(self, specs) -> None:
        """Load ``CONFIG["plugins"]`` declarations."""
        if not isinstance(specs, list):
            return
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            if not spec.get("enabled", True):
                continue
            path = str(spec.get("class", "")).strip()
            plugin = self._instantiate(path)
            if plugin is not None:
                self.register(plugin)

    def load_entry_points(self, group: str = ENTRY_POINT_GROUP) -> None:
        """Auto-load installed third-party plugins (no allowlist)."""
        try:
            eps = metadata.entry_points(group=group)
        except Exception as exc:  # noqa: BLE001 — metadata backends vary
            _LOG.warning("entry-point scan for %s failed: %s", group, exc)
            return
        for ep in eps:
            try:
                obj = ep.load()
                plugin = obj() if isinstance(obj, type) else obj
            except Exception as exc:  # noqa: BLE001 — third-party trust boundary
                _LOG.warning("entry point %s failed to load: %s", ep.name, exc)
                continue
            if isinstance(plugin, Plugin):
                self.register(plugin)
            else:
                _LOG.warning("entry point %s is not a gaworld Plugin; skipped", ep.name)

    @staticmethod
    def _instantiate(path: str) -> Plugin | None:
        if ":" not in path:
            _LOG.warning("plugin class path %r must be `module:Class`", path)
            return None
        module_name, cls_name = (part.strip() for part in path.split(":", 1))
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, cls_name)
            plugin = cls()
        except Exception as exc:  # noqa: BLE001 — config trust boundary
            _LOG.warning("failed to load plugin %s: %s", path, exc)
            return None
        if not isinstance(plugin, Plugin):
            _LOG.warning("%s is not a gaworld Plugin subclass; skipped", path)
            return None
        return plugin

    # -- lifecycle ----------------------------------------------------------

    def setup_all(self, ctx: "SimContext") -> list[str]:
        """Set up plugins in dependency order; return active plugin ids.

        A plugin whose dependency is missing, or whose ``setup`` raises, is
        deactivated with a warning (trust-boundary policy, same as the bus).
        """
        order = self._topo_order()
        active: list[str] = []
        for pid in order:
            plugin = self._plugins[pid]
            missing = [dep for dep in plugin.requires if dep not in active]
            if missing:
                _LOG.warning("plugin `%s` skipped: missing dependencies %s", pid, missing)
                continue
            try:
                plugin.setup(ctx)
            except Exception as exc:  # noqa: BLE001 — plugin trust boundary
                _LOG.warning("plugin `%s` setup failed: %s", pid, exc)
                continue
            active.append(pid)
        self._setup_order = active
        return list(active)

    def teardown_all(self, ctx: "SimContext") -> None:
        for pid in reversed(self._setup_order):
            try:
                self._plugins[pid].teardown(ctx)
            except Exception as exc:  # noqa: BLE001 — plugin trust boundary
                _LOG.warning("plugin `%s` teardown failed: %s", pid, exc)
        self._setup_order = []

    # -- queries ----------------------------------------------------------

    def get(self, plugin_id: str) -> Plugin | None:
        return self._plugins.get(plugin_id)

    def ids(self) -> list[str]:
        return list(self._plugins)

    def active_ids(self) -> list[str]:
        return list(self._setup_order)

    def _topo_order(self) -> list[str]:
        """Kahn topological sort on `requires`; cycles fall back to input order."""
        pending = dict(self._plugins)
        resolved: list[str] = []
        while pending:
            ready = [
                pid for pid, p in pending.items()
                if all(dep in resolved or dep not in self._plugins for dep in p.requires)
            ]
            if not ready:
                _LOG.warning("plugin dependency cycle among %s; using registration order", list(pending))
                resolved.extend(pending)
                break
            for pid in ready:
                resolved.append(pid)
                del pending[pid]
        return resolved
