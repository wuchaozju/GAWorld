"""Tick sync between the simulators sharing one distributed world.

Each simulator of the world -- the hub's and every node's -- reports its
position at the start of every tick and waits until no live participant is
behind it. It waits at most ``cluster.sync_timeout_seconds`` (default 60;
0 = never wait), then goes on alone and records ``cluster.sync_timeout``: a
slow or vanished machine never stops the world, the same way an absent player
does not. Cross-machine influence travels as messages read at the next
perception anyway, so the sync is loose on purpose.

Inactive unless the run was started as part of a distributed world
(``cluster.enabled`` with ``hub_url`` / ``token`` / ``run_id``, written by the
dashboard or the node process).
"""

from __future__ import annotations

import time
from typing import Any

import requests

from gaworld.kernel import Plugin

DEFAULT_TIMEOUT = 60.0
POLL_SECONDS = 0.5
REQUEST_TIMEOUT = 5.0


class ClusterSyncPlugin(Plugin):
    id = "cluster"

    def setup(self, ctx: Any) -> None:
        self.ctx = ctx
        ctx.bus.on("on_time_tick", self.wait_for_nodes)

    def _cfg(self, ctx: Any) -> dict[str, Any]:
        cfg = ctx.config.get("cluster") or {}
        return cfg if isinstance(cfg, dict) else {}

    def _post(self, cfg: dict[str, Any], day: Any, time_str: Any) -> dict[str, Any]:
        response = requests.post(
            str(cfg["hub_url"]).rstrip("/") + "/api/cluster/node/sync",
            json={"run_id": cfg.get("run_id", ""), "day": day, "time": time_str},
            headers={"Authorization": f"Bearer {cfg['token']}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"go": True}

    def wait_for_nodes(self, hook_ctx: dict[str, Any]) -> None:
        ctx = hook_ctx.get("sim") or self.ctx
        cfg = self._cfg(ctx)
        if not cfg.get("enabled") or not cfg.get("hub_url") or not cfg.get("token"):
            return
        seconds = float(cfg.get("sync_timeout_seconds", DEFAULT_TIMEOUT) or 0)
        day, time_str = hook_ctx.get("day"), hook_ctx.get("time_str")
        from gaworld.kernel import remote

        deadline = time.time() + max(0.0, seconds)
        waiting: list[str] = []
        while True:
            try:
                answer = self._post(cfg, day, time_str)
            except (requests.RequestException, ValueError) as exc:
                # The hub being unreachable is no reason to stop this machine.
                ctx.recorder.record(
                    "cluster.sync_error", {"day": day, "time": time_str, "error": str(exc)[:300]}
                )
                return
            if answer.get("go") or seconds <= 0:
                return
            waiting = list(answer.get("waiting_for") or [])
            if time.time() >= deadline:
                ctx.recorder.record(
                    "cluster.sync_timeout",
                    {"day": day, "time": time_str, "waited_seconds": seconds, "waiting_for": waiting},
                )
                return
            time.sleep(POLL_SECONDS)
            # Players' actions keep arriving while we wait; take them now.
            remote.drain(ctx)


__all__ = ["ClusterSyncPlugin"]
