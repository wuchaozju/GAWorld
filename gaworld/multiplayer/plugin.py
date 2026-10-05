"""Let a person play a resident of a running simulation.

The dashboard owns who plays whom (a two-minute lease the player's browser
keeps renewing) and reaches the simulator only through the kernel's
intervention queue, applied at the next tick. This plugin keeps the
simulator's side:

- ``player_claim(agent_id, player, until)`` / ``player_release(agent_id)``:
  the resident is being played until wall-clock ``until``; a lapsed lease
  hands it back to the model without anyone having to say so.
- ``player_act(agent_id, text)``: what the player wants the resident to do
  next. It is shown inside that step's perception -- so planning and moving
  follow it like any other intention -- and becomes the step's action.
- ``player_say(agent_id, target_id, text)``: heard by the target at its next
  perception (and remembered by the speaker the same way). In a distributed
  world the target may live on another machine: then this simulator only has
  the speaker, takes the target's name from ``target_name``, and the hub sends
  the target's machine ``player_hear(agent_id, speaker_id, speaker_name, text)``.

A resident nobody plays is an ordinary model-driven resident: a player being
offline never stops the world. ``multiplayer.wait_for_players_seconds``
(default 0) makes each tick wait up to that long for every current player to
act, for a class that wants to talk a round through.

Everything a player does is recorded (``multiplayer.act`` / ``multiplayer.say``),
which is also how every other browser watching the world sees it live.
"""

from __future__ import annotations

import time
from typing import Any

from gaworld.kernel import Plugin

MAX_TEXT = 500
WAIT_POLL_SECONDS = 0.5


def _agent(ctx: Any, agent_id: Any) -> dict[str, Any]:
    agent = ctx.agents_by_id.get(agent_id)
    if agent is None:
        try:
            agent = ctx.agents_by_id.get(int(agent_id))
        except (TypeError, ValueError):
            agent = None
    if agent is None:
        raise ValueError(f"unknown agent {agent_id!r}")
    return agent


def _clip(text: Any) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("text is required")
    return text[:MAX_TEXT]


class MultiplayerPlugin(Plugin):
    id = "multiplayer"

    def setup(self, ctx: Any) -> None:
        self.ctx = ctx
        controller = ctx.controller
        controller.register_intervention("player_claim", self.claim)
        controller.register_intervention("player_release", self.release)
        controller.register_intervention("player_act", self.act)
        controller.register_intervention("player_say", self.say)
        controller.register_intervention("player_hear", self.hear)
        ctx.bus.on("perception.sections", self.sections)
        ctx.bus.on("action.selected", self.override_action)
        ctx.bus.on("on_agent_post_step", self.consume)
        ctx.bus.on("on_time_tick", self.wait_for_players)

    # -- state ------------------------------------------------------------

    def _state(self, ctx: Any) -> dict[str, Any]:
        state = ctx.plugin_state(self.id)
        state.setdefault("claims", {})  # agent id -> {"player", "until"}
        state.setdefault("intents", {})  # agent id -> text for its next step
        state.setdefault("heard", {})  # agent id -> lines for its next perception
        state.setdefault("applied", set())  # agent ids whose intent became this step's action
        return state

    def _live_claim(self, ctx: Any, agent_id: int) -> dict[str, Any] | None:
        claim = self._state(ctx)["claims"].get(agent_id)
        return claim if claim and claim["until"] > time.time() else None

    # -- interventions ----------------------------------------------------

    def claim(self, ctx: Any, agent_id: Any = None, player: str = "", until: float = 0.0) -> dict[str, Any]:
        agent = _agent(ctx, agent_id)
        aid = int(agent["id"])
        self._state(ctx)["claims"][aid] = {"player": str(player or ""), "until": float(until)}
        return {"agent_id": aid, "until": float(until)}

    def release(self, ctx: Any, agent_id: Any = None) -> dict[str, Any]:
        aid = int(_agent(ctx, agent_id)["id"])
        state = self._state(ctx)
        state["claims"].pop(aid, None)
        state["intents"].pop(aid, None)
        return {"agent_id": aid}

    def act(self, ctx: Any, agent_id: Any = None, text: str = "") -> dict[str, Any]:
        agent = _agent(ctx, agent_id)
        aid = int(agent["id"])
        claim = self._live_claim(ctx, aid)
        if claim is None:
            raise ValueError(f"agent {aid} is not being played")
        intent = _clip(text)
        self._state(ctx)["intents"][aid] = intent
        ctx.recorder.record(
            "multiplayer.act",
            {"agent_id": aid, "agent_name": agent.get("name", ""), "player": claim["player"], "text": intent},
        )
        return {"agent_id": aid, "queued_for": "next step"}

    def say(
        self, ctx: Any, agent_id: Any = None, target_id: Any = None, text: str = "", target_name: str = ""
    ) -> dict[str, Any]:
        speaker = _agent(ctx, agent_id)
        sid = int(speaker["id"])
        try:
            target: dict[str, Any] | None = _agent(ctx, target_id)
        except ValueError:
            # A resident on another machine of a distributed world.
            if not target_name:
                raise
            target = None
        tid = int(target["id"]) if target else int(target_id)
        claim = self._live_claim(ctx, sid)
        if claim is None:
            raise ValueError(f"agent {sid} is not being played")
        line = _clip(text)
        heard = self._state(ctx)["heard"]
        speaker_name = speaker.get("name", f"#{sid}")
        target_name = target.get("name", f"#{tid}") if target else str(target_name)
        if target:
            heard.setdefault(tid, []).append(f"{speaker_name}对你说：「{line}」")
        heard.setdefault(sid, []).append(f"你对{target_name}说了：「{line}」")
        ctx.recorder.record(
            "multiplayer.say",
            {
                "agent_id": sid,
                "agent_name": speaker_name,
                "target_id": tid,
                "target_name": target_name,
                "player": claim["player"],
                "text": line,
            },
        )
        return {"agent_id": sid, "target_id": tid}

    def hear(
        self, ctx: Any, agent_id: Any = None, speaker_id: Any = None, speaker_name: str = "", text: str = ""
    ) -> dict[str, Any]:
        """What a played resident on another machine said to one of ours.

        The speaker's machine has already recorded the line; this only puts it
        in the listener's next perception.
        """
        aid = int(_agent(ctx, agent_id)["id"])
        name = str(speaker_name or f"#{speaker_id}")
        self._state(ctx)["heard"].setdefault(aid, []).append(f"{name}对你说：「{_clip(text)}」")
        return {"agent_id": aid}

    # -- hooks ------------------------------------------------------------

    def sections(self, hook_ctx: dict[str, Any]) -> list[str] | None:
        ctx = hook_ctx.get("sim") or self.ctx
        aid = int(hook_ctx["agent"]["id"])
        state = self._state(ctx)
        lines = [f"【刚才发生的对话】{line}" for line in state["heard"].pop(aid, [])]
        intent = state["intents"].get(aid)
        if intent and self._live_claim(ctx, aid):
            lines.append(f"【你此刻的决定】{intent}。这是你自己拿定的主意，接下来照此行动。")
        return lines or None

    def override_action(self, value: Any, hook_ctx: dict[str, Any]) -> Any:
        ctx = hook_ctx.get("sim") or self.ctx
        aid = int(hook_ctx["agent"]["id"])
        state = self._state(ctx)
        intent = state["intents"].get(aid)
        if not intent or not self._live_claim(ctx, aid):
            return None
        state["applied"].add(aid)
        return intent

    def consume(self, hook_ctx: dict[str, Any]) -> None:
        """An intent drives exactly one action.

        Only a step that actually chose an action uses it up: a resident still
        travelling (the step's action is the trip) keeps the intent, and keeps
        seeing it, until it arrives and acts.
        """
        ctx = hook_ctx.get("sim") or self.ctx
        aid = int(hook_ctx["agent"]["id"])
        state = self._state(ctx)
        if aid in state["applied"]:
            state["applied"].discard(aid)
            state["intents"].pop(aid, None)

    def wait_for_players(self, hook_ctx: dict[str, Any]) -> None:
        ctx = hook_ctx.get("sim") or self.ctx
        seconds = float((ctx.config.get("multiplayer") or {}).get("wait_for_players_seconds") or 0)
        if seconds <= 0:
            return
        from gaworld.kernel import remote

        deadline = time.time() + seconds
        while time.time() < deadline:
            state = self._state(ctx)
            waiting = [
                aid
                for aid in list(state["claims"])
                if self._live_claim(ctx, aid) and aid not in state["intents"]
            ]
            if not waiting:
                return
            time.sleep(WAIT_POLL_SECONDS)
            # The players' actions arrive through the queue; take them now
            # rather than at the next tick.
            remote.drain(ctx)


__all__ = ["MultiplayerPlugin"]
