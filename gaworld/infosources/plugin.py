"""InfoSourcesPlugin — the outside world's feeds and each resident's media diet.

- ``agents.built`` (observe): load the registry, refresh the feed cache (real
  time TTL, so a fast run does not re-fetch), publish it through
  :func:`gaworld.infosources.feed.set_runtime`, and give every resident a media
  diet. Runs before the simulator's own news bootstrap, so the first info-seek
  of day 1 already reads from the diet.
- ``on_day_start`` (observe): re-run the TTL-gated refresh (a multi-hour real
  run keeps meeting new stories) and rebuild the diets (``platform_dependence``
  drifts during a run; the job can change).
- ``on_simulation_end`` (observe): drop the runtime holder.
- ``inject_info_item`` (intervention, also ``POST /api/interventions/
  inject_info_item``): put one item at the top of a registered source for the
  rest of the run, so its spread through the residents who read that source
  can be followed on the ``infosources.read`` record table.

The diet is stored at ``agent["ext"]["infosources"]["diet"]`` and read by
``gaworld.sim._news`` through :func:`gaworld.infosources.diet.diet_of`; a copy
of all diets goes to ``output/infosources/diets.json`` so "who reads what" is
an inspectable research artefact, not a side effect buried in memory logs.
"""

from __future__ import annotations

import json
from pathlib import Path

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.infosources.plugin")


class InfoSourcesPlugin(Plugin):
    id = "infosources"

    def setup(self, ctx):
        from gaworld.infosources import channels as channels_impl
        from gaworld.infosources import diet as diet_impl
        from gaworld.infosources import feed as feed_impl
        from gaworld.infosources import registry as registry_impl

        self._channels = channels_impl
        self._diet = diet_impl
        self._feed = feed_impl
        self._registry = registry_impl
        news_cfg = ctx.config.get("news", {}) or {}
        self._cfg = dict(news_cfg.get("sources", {}) or {})
        self._enabled = bool(news_cfg.get("enabled", True)) and bool(self._cfg.get("enabled", True))
        self._sources = []
        self._injected = []
        self._recorder = ctx.recorder
        self._diets_path = self.output_dir(ctx) / "diets.json"
        if not self._enabled:
            return
        ctx.controller.register_intervention("inject_info_item", self._inject)
        ctx.bus.on("agents.built", self._on_agents_built)
        ctx.bus.on("on_day_start", self._on_day_start)
        ctx.bus.on("on_simulation_end", self._on_simulation_end)

    # -- hooks ---------------------------------------------------------------

    def _on_agents_built(self, hook_ctx):
        self._sources = self._registry.load_registry(
            self._cfg.get("registry_path", self._registry.DEFAULT_REGISTRY_PATH)
        )
        if not self._sources:
            _LOG.warning("infosources: registry is empty; residents keep the legacy news path only")
        self._refresh()
        self._build_diets(hook_ctx.get("agents") or [])

    def _on_day_start(self, hook_ctx):
        if not self._sources:
            return
        self._refresh()
        self._build_diets(hook_ctx.get("agents") or [])

    def _on_simulation_end(self, hook_ctx):
        self._feed.set_runtime(None)

    def _inject(self, ctx, source_id="", title="", excerpt="", url=""):
        """Top-of-feed item on ``source_id`` until the run ends.

        Kept in ``self._injected`` and re-applied after every refresh: the
        refresh reloads the cache from disk, and writing the item to that disk
        cache instead would leak a fabricated story into later runs. Without a
        real URL it gets a ``gaworld://`` one, so per-day seen-tracking still
        stops a resident re-reading it and the full-page fetch skips it.
        """
        from gaworld.infosources.schema import InfoItem

        rt = self._feed.runtime()
        if rt is None:
            raise ValueError("information sources are not running (news.sources.enabled?)")
        source = rt.sources.get(str(source_id))
        if source is None:
            raise ValueError(f"unknown source_id {source_id!r}; registered: {sorted(rt.sources)}")
        title = str(title or "").strip()
        if not title:
            raise ValueError("inject_info_item requires a `title`")
        n = len(self._injected) + 1
        item = InfoItem(
            source_id=source.id,
            kind=source.kind,
            title=title,
            url=str(url or "").strip() or f"gaworld://injected/{n}",
            excerpt=str(excerpt or "").strip(),
            published_at=f"Day {ctx.clock.day} {ctx.clock.time_str}",
            meta={"injected": True},
        )
        self._injected.append(item)
        self._apply_injected(rt.cache)
        if ctx.recorder is not None:
            ctx.recorder.record("infosources.injected", item.to_dict())
        return item.to_dict()

    def _apply_injected(self, cache):
        for item in self._injected:
            rows = [r for r in cache.items.get(item.source_id, []) if r.key != item.key]
            cache.items[item.source_id] = [item] + rows

    # -- work ----------------------------------------------------------------

    def _refresh(self):
        if not self._sources:
            return
        timeout = int(self._cfg.get("timeout", 10))
        limit = int(self._cfg.get("per_source_limit", self._feed.DEFAULT_PER_SOURCE_LIMIT))
        cache = self._feed.refresh(
            self._sources,
            self._cfg.get("feed_cache_path", "output/infosources/feed.json"),
            fetch_fn=lambda source: self._channels.fetch_source(source, timeout=timeout, limit=limit),
            ttl_hours=float(self._cfg.get("ttl_hours", self._feed.DEFAULT_TTL_HOURS)),
            per_source_limit=limit,
        )
        self._feed.set_runtime(
            self._feed.FeedRuntime(
                cache=cache,
                sources=self._registry.by_id(self._sources),
                settings=dict(self._cfg),
                recorder=self._recorder,
            )
        )
        self._apply_injected(cache)

    def _build_diets(self, agents):
        if not self._sources:
            return
        from gaworld.sim._news import _extract_interest_keywords

        diet_cfg = self._cfg.get("diet", {}) or {}
        report = {}
        for agent in agents:
            diet = self._diet.build_media_diet(
                agent,
                self._sources,
                interests=_extract_interest_keywords(agent),
                config=diet_cfg,
            )
            agent.setdefault("ext", {}).setdefault(self.id, {})["diet"] = diet
            report[str(agent.get("id"))] = {
                "name": agent.get("name", ""),
                "job": agent.get("job", ""),
                "diet": diet,
            }
        try:
            path = Path(self._diets_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            _LOG.warning("infosources: diets not written (%s): %s", self._diets_path, exc)


__all__ = ["InfoSourcesPlugin"]
