"""PublicSectorPlugin — the government in office and what its policies do.

Inert unless ``public_sector.enabled``. While on:

- ``on_simulation_start`` (priority 50, ahead of the economy's 0): snapshot
  the run's economy config as the *base*, then rewrite ``config["economy"]``
  in place from the government's policies. The economy reads its config on
  every hook, so tax, social insurance, reimbursement and the minimum wage
  follow from here on.
- ``on_day_start`` (priority 50): apply any ``schedule`` entry that is due —
  a change of government re-derives the economy from the base, never from
  the previous government's version.
- ``on_day_end`` (priority 5, before the economy's settlement at 0): pay
  unemployment benefit, pension and basic income out of the government pool
  into residents' checking accounts. Both sides are booked, so the money
  conservation audit still holds; a pool that goes negative is a deficit.
- ``on_day_end`` (priority -50, after the economy and family settle): record
  the day's fiscal row to ``public_sector.daily``.
- ``perception.compose``: each resident's first perception of a day carries
  the government brief (and what they were paid yesterday); a change of
  government is announced to everyone at their next perception.
- intervention ``public_sector.set_government(government, note)``: the
  dashboard's "switch now" — applied at the next tick through the kernel
  queue.
- ``on_simulation_end`` (priority -100): put the base economy back, so an
  in-process caller's CONFIG is left as it was found.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from gaworld.kernel import Plugin


class PublicSectorPlugin(Plugin):
    id = "public_sector"

    def setup(self, ctx):
        from gaworld.public_sector import policy

        self._policy = policy
        cfg = ctx.config.get("public_sector") or {}
        self._enabled = bool(cfg.get("enabled", False))
        if not self._enabled:
            return
        self._announce = bool(cfg.get("announce", True))
        self._schedule = [e for e in cfg.get("schedule") or [] if isinstance(e, dict)]
        ctx.controller.register_intervention("public_sector.set_government", self.set_government)
        ctx.bus.on("on_simulation_start", self._start, priority=50)
        ctx.bus.on("on_day_start", self._day_start, priority=50)
        ctx.bus.on("on_day_end", self._pay_transfers, priority=5)
        ctx.bus.on("on_day_end", self._record_day, priority=-50)
        ctx.bus.on("perception.compose", self._brief, priority=5)
        ctx.bus.on("on_simulation_end", self._restore, priority=-100)

    # -- government changes ----------------------------------------------------

    def _state(self, ctx) -> dict[str, Any]:
        return ctx.plugin_state(self.id)

    def _apply(self, ctx, government_id: str | None, *, day: Any, note: str, source: str) -> dict[str, Any]:
        state = self._state(ctx)
        gid, government = self._policy.resolve(ctx.config, government_id)
        economy = self._policy.derive_economy(state["base_economy"], self._policy.policies_of(government))
        live = ctx.config.setdefault("economy", {})
        live.clear()
        live.update(economy)
        previous = state.get("government")
        state.update(government=gid, since_day=day, announce_seq=state.get("announce_seq", 0) + 1)
        row = {
            "run": state["run"],
            "day": day,
            "government": gid,
            "name": government.get("name", gid),
            "previous": previous,
            "source": source,
            "note": str(note or "")[:200],
            "policies": self._policy.policies_of(government),
        }
        state.setdefault("history", []).append(row)
        if ctx.recorder is not None:
            ctx.recorder.record("public_sector.change", row)
        return row

    def set_government(self, ctx, government: str = "", note: str = "") -> dict[str, Any]:
        if not government:
            raise ValueError("set_government requires `government`")
        try:
            return self._apply(ctx, str(government), day=ctx.clock.day, note=note, source="intervention")
        except KeyError:
            raise ValueError(f"unknown government `{government}`") from None

    # -- hooks -----------------------------------------------------------------

    def _start(self, hook_ctx):
        ctx = hook_ctx["sim"]
        state = self._state(ctx)
        state["base_economy"] = deepcopy(ctx.config.get("economy") or {})
        # Records are appended across runs; the id lets a reader keep one run.
        state["run"] = uuid.uuid4().hex[:8]
        state["applied_schedule"] = set()
        try:
            self._apply(ctx, None, day=0, note="", source="config")
        except KeyError as exc:
            raise ValueError(f"public_sector.government `{exc.args[0]}` is not configured") from None

    def _day_start(self, hook_ctx):
        ctx = hook_ctx["sim"]
        state = self._state(ctx)
        try:
            today = int(hook_ctx.get("day") or 0)
        except (TypeError, ValueError):
            return
        # `<=` rather than `==`: a fast-forward step can start past the
        # scheduled day, and the change must still happen.
        for index, entry in enumerate(self._schedule):
            if index in state["applied_schedule"]:
                continue
            try:
                due = int(entry.get("day"))
            except (TypeError, ValueError):
                continue
            if due <= today:
                state["applied_schedule"].add(index)
                self._apply(
                    ctx, entry.get("government"), day=today, note=entry.get("note", ""), source="schedule"
                )

    def _recipients(self, agent: dict[str, Any], econ: dict[str, Any]) -> set[str]:
        from gaworld.economy import finance

        status = finance.employment_status(agent)
        groups = {"everyone"}
        if status == finance.UNEMPLOYED_STATUS or econ.get("_layoff_days_remaining", 0):
            groups.add("unemployed")
        if status == "retired":
            groups.add("retired")
        return groups

    def _pay_transfers(self, hook_ctx):
        ctx = hook_ctx["sim"]
        state = self._state(ctx)
        _gid, government = self._policy.resolve(ctx.config, state.get("government"))
        amounts = self._policy.transfer_amounts(self._policy.policies_of(government))
        totals = dict.fromkeys(amounts, 0.0)
        counts = dict.fromkeys(amounts, 0)
        state["today"] = {"totals": totals, "recipients": counts}
        if not any(amounts.values()):
            return
        economy = (hook_ctx.get("extension_state") or {}).get("economy_module") or {}
        if not economy.get("enabled"):
            return
        sectors = economy.get("sectors")
        try:
            days = max(1, int(hook_ctx.get("period_days") or 1))
        except (TypeError, ValueError):
            days = 1
        day = hook_ctx.get("day")
        for agent in hook_ctx.get("agents") or []:
            if not isinstance(agent, dict) or agent.get("family_dependant"):
                continue
            econ = agent.get("economy")
            if not isinstance(econ, dict):
                continue
            groups = self._recipients(agent, econ)
            paid: dict[str, float] = {}
            for key, amount in amounts.items():
                if amount > 0 and self._policy.TRANSFERS[key][0] in groups:
                    paid[key] = round(amount * days, 2)
            if not paid:
                continue
            total = round(sum(paid.values()), 2)
            accounts = econ.setdefault("accounts", {})
            accounts["checking"] = round(float(accounts.get("checking", 0) or 0) + total, 2)
            econ["daily_income"] = float(econ.get("daily_income", 0) or 0) + total
            econ["lifetime_income"] = float(econ.get("lifetime_income", 0) or 0) + total
            if isinstance(sectors, dict):
                sectors["government"] = round(float(sectors.get("government", 0) or 0) - total, 2)
            for key, value in paid.items():
                totals[key] = round(totals[key] + value, 2)
                counts[key] += 1
            ctx.agent_ext(agent, self.id)["last_paid"] = {"day": day, "items": paid}

    def _record_day(self, hook_ctx):
        ctx = hook_ctx["sim"]
        if ctx.recorder is None:
            return
        state = self._state(ctx)
        economy = (hook_ctx.get("extension_state") or {}).get("economy_module") or {}
        sectors = economy.get("sectors") if isinstance(economy.get("sectors"), dict) else {}
        today = state.get("today") or {}
        ctx.recorder.record(
            "public_sector.daily",
            {
                "run": state.get("run"),
                "day": hook_ctx.get("day"),
                "government": state.get("government"),
                "transfers": today.get("totals", {}),
                "recipients": today.get("recipients", {}),
                "transfers_total": round(sum((today.get("totals") or {}).values()), 2),
                "government_balance": sectors.get("government"),
            },
        )

    def _brief(self, hook_ctx):
        if not self._announce:
            return None
        ctx = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        state = self._state(ctx)
        ext = ctx.agent_ext(agent, self.id)
        day = hook_ctx.get("day")
        seq = state.get("announce_seq", 0)
        lines = []
        if ext.get("seen_seq") != seq and len(state.get("history", [])) > 1:
            last = state["history"][-1]
            lines.append(
                f"本市政府更迭：{last['name']}上任" + (f"（{last['note']}）" if last.get("note") else "")
            )
        elif ext.get("brief_day") == day:
            return None
        ext["seen_seq"] = seq
        ext["brief_day"] = day
        _gid, government = self._policy.resolve(ctx.config, state.get("government"))
        lines.append(self._policy.brief(government))
        last_paid = ext.pop("last_paid", None)
        if last_paid:
            items = "、".join(
                f"{self._policy.TRANSFERS[key][1]} {value:g} 元" for key, value in last_paid["items"].items()
            )
            lines.append(f"你上次结算领到：{items}")
        return ["公共部门：" + " ".join(lines)]

    def _restore(self, hook_ctx):
        ctx = hook_ctx["sim"]
        base = self._state(ctx).get("base_economy")
        if base is None:
            return
        live = ctx.config.setdefault("economy", {})
        live.clear()
        live.update(deepcopy(base))
