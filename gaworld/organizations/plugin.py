"""Persistent organizations participate through the common simulation bus."""

from __future__ import annotations

from typing import Any

from gaworld.kernel import Plugin


def OrganizationService(*args: Any, **kwargs: Any) -> Any:
    """Load the stateful service only when the feature starts."""
    from gaworld.organizations.service import OrganizationService as Service

    return Service(*args, **kwargs)


class OrganizationsPlugin(Plugin):
    id = "organizations"
    requires = ("economy",)

    def setup(self, ctx: Any) -> None:
        if not (ctx.config.get(self.id) or {}).get("enabled", False):
            return
        self.ctx = ctx
        # Startup follows economy initialization; day-end follows family
        # settlement, so a checkpoint includes all counterparties.
        ctx.bus.on("on_simulation_start", self._start, priority=-5, critical=True)
        # Synchronize returning workers before economy snapshots or travel pay;
        # monetary decisions still follow economy's daily counter reset.
        ctx.bus.on("on_day_start", self._prepare_day, priority=10, critical=True)
        ctx.bus.on("on_day_start", self._process_day, priority=-5, critical=True)
        ctx.bus.on("on_day_end", self._finish_day, priority=-20, critical=True)
        ctx.bus.on("on_simulation_end", self._close, priority=-20, critical=True)
        ctx.bus.on("perception.sections", self._perception, critical=True)
        ctx.bus.on("fast_forward.perception.sections", self._perception, critical=True)
        ctx.bus.on("action.candidates", self._candidates, critical=True)
        ctx.bus.on("on_agent_post_step", self._post_step, priority=-5, critical=True)
        ctx.bus.on("action.executed", self._executed, critical=True)
        ctx.bus.on("life.event.applied", self._employment_changed, critical=True)

    def _service(self) -> Any:
        return self.ctx.plugin_state(self.id).get("service")

    def _start(self, context: dict[str, Any]) -> None:
        service = OrganizationService(
            self.ctx.config,
            context.get("agents") or self.ctx.agents,
            context,
            recorder=self.ctx.recorder,
        )
        self.ctx.plugin_state(self.id)["service"] = service
        try:
            service.start(int(context.get("day", 1) or 1))
        except BaseException:
            if hasattr(service, "close"):
                service.close()
            self.ctx.plugin_state(self.id).pop("service", None)
            raise

    def _employment_changed(self, context: dict[str, Any]) -> None:
        from gaworld.economy.finance import is_employment_event

        event = context.get("life_event") or {}
        service = self._service()
        if service is not None and is_employment_event(event):
            service.release_employment(
                context["agent"], int(context["day"]), str(event.get("template_key", ""))
            )

    def _prepare_day(self, context: dict[str, Any]) -> None:
        service = self._service()
        if service is not None:
            service.prepare_day(int(context["day"]))

    def _process_day(self, context: dict[str, Any]) -> None:
        service = self._service()
        if service is not None:
            service.process_day(int(context["day"]))

    def _finish_day(self, context: dict[str, Any]) -> None:
        service = self._service()
        if service is not None:
            service.finish_day(int(context["day"]))

    def _close(self, context: dict[str, Any]) -> None:
        service = self._service()
        if service is not None:
            service.close()
            self.ctx.plugin_state(self.id).pop("service", None)

    def teardown(self, ctx: Any) -> None:
        # A critical startup failure can happen before normal end hooks.
        # Closing is safe twice because the service reference is removed.
        if hasattr(self, "ctx"):
            self._close({})

    def _perception(self, context: dict[str, Any]) -> list[str]:
        service = self._service()
        agent = context.get("agent")
        if service is None or agent is None:
            return []
        section = service.perception(agent)
        return [section] if section else []

    def _candidates(self, context: dict[str, Any]) -> list[str]:
        service = self._service()
        agent = context.get("agent")
        if service is None or agent is None:
            return []
        return service.candidates(agent, str(context.get("activity", "")))

    def _post_step(self, context: dict[str, Any]) -> None:
        step = context.get("step") or {}
        self._executed({**context, "action": step.get("action", "")})

    def _executed(self, context: dict[str, Any]) -> None:
        action = context.get("action")
        # A narrative outcome never becomes a command. The service validates
        # the exact controlled identifier and current eligibility again.
        if not isinstance(action, str) or not action.startswith("org:"):
            return
        service = self._service()
        if service is not None and context.get("agent") is not None:
            service.handle_action(
                context["agent"], action, int(context["day"]), str(context.get("time_str", ""))
            )
