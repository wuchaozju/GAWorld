"""RealWorkRuntime — single object that wires the subsystem together.

The simulator only needs to interact with this object:

    rt = RealWorkRuntime.create(CONFIG, agents, llm_fn=call_llm)
    rt.start()
    ...
    outcome = rt.router.maybe_dispatch(agent, ...)
    consumed = rt.absorb_for(agent, sim_day=..., sim_time=...)
    ...
    rt.tick_day(sim_day)   # at day boundaries

This keeps the diff in ``generative_city_sim.py`` tiny.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable, Optional

from gaworld.logging_setup import get_logger
from gaworld.skills.market import SkillMarket
from gaworld.work.adapters import build_default_adapters
from gaworld.work.adapters.base import AdapterContext
from gaworld.work.capabilities import bootstrap_all_agents
from gaworld.work.ingest import absorb_completed_for
from gaworld.work.market import JobMarket
from gaworld.work.queue import WorkQueue
from gaworld.work.router import RealWorkRouter
from gaworld.work.schemas import AgentCapabilities, WorkResult
from gaworld.work.skill_lookup import make_market_hook
from gaworld.work.worker import WorkerPool

_LOG = get_logger("gaworld.work.runtime")


class RealWorkRuntime:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        capabilities: dict[int, AgentCapabilities],
        queue: WorkQueue,
        market: Optional[JobMarket],
        worker: WorkerPool,
        router: RealWorkRouter,
    ) -> None:
        self.config = config
        self.capabilities = capabilities
        self.queue = queue
        self.market = market
        self.worker = worker
        self.router = router
        self._started = False

    # ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        full_config: dict[str, Any],
        agents: Iterable[dict[str, Any]],
        *,
        llm_fn: Callable[[str], str],
    ) -> Optional["RealWorkRuntime"]:
        """Create a runtime if real_work is enabled, else return None."""

        if not isinstance(full_config, dict):
            return None
        rw = full_config.get("real_work")
        if not isinstance(rw, dict) or not rw.get("enabled"):
            return None

        artifacts_dir = str(rw.get("artifacts_dir", "output/work"))
        os.makedirs(artifacts_dir, exist_ok=True)

        # Capabilities (LLM call, possibly cached).
        cache_path = str(rw.get("capabilities_cache", "output/work/capabilities.json"))
        capabilities = bootstrap_all_agents(list(agents), cache_path, llm=llm_fn)
        _LOG.info("derived capabilities for %d agents (cache=%s)", len(capabilities), cache_path)

        # Queue.
        queue = WorkQueue(str(rw.get("queue_path", "output/work/queue.jsonl")))

        # Market (optional).
        market: Optional[JobMarket] = None
        market_cfg = rw.get("market", {}) if isinstance(rw.get("market"), dict) else {}
        if market_cfg.get("enabled", False):
            market = JobMarket(
                store_path=str(market_cfg.get("store_path", "output/work/market.jsonl")),
                seed_path=str(market_cfg.get("seed_path", "gaworld/work/market_seed.json")),
                expire_after_sim_days=int(market_cfg.get("expire_after_sim_days", 5)),
                auto_replenish=bool(market_cfg.get("auto_replenish", True)),
                replenish_threshold=int(market_cfg.get("replenish_threshold", 5)),
            )

        # Adapters + worker.
        adapter_cfg = rw.get("adapters", {}) if isinstance(rw.get("adapters"), dict) else {}
        all_adapters = build_default_adapters()
        enabled_adapters = {
            name: adapter
            for name, adapter in all_adapters.items()
            if adapter_cfg.get(name, {}).get("enabled", True)
        }

        def _ctx_factory(adapter_name: str) -> AdapterContext:
            return AdapterContext(
                artifacts_root=artifacts_dir,
                llm=llm_fn,
                config=adapter_cfg.get(adapter_name, {}),
            )

        router = RealWorkRouter(
            queue=queue,
            market=market,
            capabilities=capabilities,
            config=rw,
        )

        # Online skill market (opt-in): fills a brief's free skill slots
        # on the worker thread.
        skills_cfg = full_config.get("skills")
        skills_cfg = skills_cfg if isinstance(skills_cfg, dict) else {}
        online = skills_cfg.get("online")
        brief_hook = None
        if (
            isinstance(online, dict)
            and online.get("enabled")
            and skills_cfg.get("inject_into_work_brief", True)
        ):
            skill_market = SkillMarket(
                str(online.get("cache_dir") or "output/skills_market"),
                api_base=str(online.get("api_base") or "https://skills.sh"),
                min_installs=int(online.get("min_installs", 100)),
                timeout=float(online.get("timeout_seconds", 10)),
            )
            brief_hook = make_market_hook(skill_market, router.skill_registry)

        worker = WorkerPool(
            queue=queue,
            adapters=enabled_adapters,
            ctx_factory=_ctx_factory,
            max_workers=int(rw.get("max_concurrent_tasks", 2)),
            task_timeout_seconds=int(rw.get("task_timeout_seconds", 600)),
            brief_hook=brief_hook,
        )
        return cls(
            config=rw,
            capabilities=capabilities,
            queue=queue,
            market=market,
            worker=worker,
            router=router,
        )

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self.worker.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self.worker.stop(wait=True)
        self._started = False

    def absorb_for(
        self,
        agent: dict[str, Any],
        *,
        sim_day: int,
        sim_time: str,
    ) -> list[WorkResult]:
        return absorb_completed_for(
            agent,
            queue=self.queue,
            market=self.market,
            sim_day=sim_day,
            sim_time=sim_time,
            limit=int(self.config.get("tick_ingest_limit", 5)),
            skill_registry=self.router.skill_registry,
        )

    def tick_day(self, sim_day: int) -> None:
        if self.market is not None:
            self.market.tick_day(sim_day)


__all__ = ["RealWorkRuntime"]
