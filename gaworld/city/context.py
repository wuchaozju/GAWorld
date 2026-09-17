"""The running simulation's view of its city's knowledge base.

One loader, four consumers. Everything the city knows — its industry profile
and its recent news — reaches agents through exactly these read-outs:

===============  ==========================================================
``prompt_block`` cognition prompts (via the run's ``background``)
``growth_hint``  skill/hobby selection in :mod:`gaworld.interests`
``industry_mix`` the job market in :mod:`gaworld.economy`
``rag_chunks``   each agent's ``external_info`` RAG store at bootstrap
===============  ==========================================================

Loading is cached on the bundle files' mtimes: this is read on hot paths (every
cognition step asks for the prompt block) and re-parsing two JSON files per
agent per tick would be pure waste.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from gaworld.city.knowledge import CityProfile
from gaworld.city.news import NewsCache, for_sim_day
from gaworld.city.news import prompt_block as news_prompt_block
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.city.context")

#: Parsed contexts keyed by (slug, knowledge mtime, news mtime).
_CACHE: dict[tuple, "CityContext"] = {}
_CACHE_LIMIT = 4


@dataclass
class CityContext:
    """What the simulation knows about the city it is running in."""

    slug: str = ""
    name: str = ""
    profile: CityProfile = field(default_factory=CityProfile)
    news: NewsCache = field(default_factory=NewsCache)

    @property
    def is_empty(self) -> bool:
        return self.profile.is_empty and not self.news.items

    # -- channel A: cognition prompts --------------------------------------

    def prompt_block(self, sim_day: int | None = None, *, per_day: int = 2) -> str:
        """City briefing for the background prompt, optionally with the day's news."""
        parts = [self.profile.prompt_block()]
        if sim_day is not None:
            headlines = news_prompt_block(for_sim_day(self.news, sim_day, per_day=per_day))
            if headlines:
                parts.append(f"近期本地消息：{headlines}")
        return " ".join(part for part in parts if part)

    # -- channel B: skill growth -------------------------------------------

    def growth_hint(self) -> str:
        """The economic context that should steer what residents choose to learn.

        Growing industries and unmet labour demand come first: those are the
        levers the user actually wants — a city pushing tourism should make its
        residents more likely to pick up tourism skills.
        """
        if self.profile.is_empty:
            return ""
        bits: list[str] = []
        growing = [i.name for i in self.profile.growing()]
        if growing:
            bits.append("正在发展：" + "、".join(growing[:3]))
        tops = [i.name for i in self.profile.top_industries()]
        if tops:
            bits.append("主要产业：" + "、".join(tops))
        if self.profile.labor_demand:
            bits.append("本地紧缺：" + "、".join(self.profile.labor_demand[:4]))
        return "；".join(bits)

    def signature(self) -> str:
        """Cache-key component for anything derived from ``growth_hint``.

        ``interests.profile_signature`` keys cached growth profiles on the
        agent's own fields alone. Once the city steers that derivation, two
        cities would otherwise share one cached profile and the second city's
        influence would silently never appear.
        """
        hint = self.growth_hint()
        if not hint:
            return ""
        return hashlib.md5(f"{self.slug}\x01{hint}".encode("utf-8")).hexdigest()[:12]

    # -- channel C: the job market -----------------------------------------

    def industry_mix(self) -> dict[str, float]:
        """Weights over the six economy categories, or ``{}`` when unknown."""
        return self.profile.industry_mix()

    # -- channel D: per-agent RAG ------------------------------------------

    def rag_chunks(self, *, max_chunks: int = 5) -> list[str]:
        """Short standalone facts to seed agents' external-info memory with."""
        if self.profile.is_empty:
            return []
        chunks: list[str] = []
        if self.profile.summary:
            chunks.append(f"[城市概况] {self.name}：{self.profile.summary}")
        for industry in self.profile.top_industries(limit=3):
            trend = {"growing": "正在增长", "declining": "正在萎缩", "stable": "较为稳定"}[industry.trend]
            note = f"，{industry.note}" if industry.note else ""
            chunks.append(f"[本地产业] {self.name}的{industry.name}{trend}{note}。")
        if self.profile.labor_demand:
            chunks.append(
                f"[本地就业] {self.name}目前紧缺：" + "、".join(self.profile.labor_demand[:4]) + "。"
            )
        if self.profile.priorities:
            chunks.append(f"[发展重点] {self.name}正在推进：" + "、".join(self.profile.priorities[:3]) + "。")
        return chunks[:max_chunks]


_EMPTY = CityContext()


def _read_json(path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_context(config: Any = None, *, root: Any = None) -> CityContext:
    """The selected city's knowledge, or an empty context when there is none.

    Never raises: a missing, deleted or malformed bundle degrades to "the
    simulation knows nothing special about its city", which is exactly how
    every run behaved before this feature existed.
    """
    from gaworld.settings import CONFIG

    cfg = config if isinstance(config, dict) else CONFIG
    slug = str((cfg or {}).get("city") or "").strip()
    if not slug:
        return _EMPTY

    try:
        from gaworld.city.bundle import resolve_city

        bundle = resolve_city(slug, root)
    except Exception:  # noqa: BLE001 - see docstring
        return _EMPTY

    def mtime(path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    key = (bundle.slug, mtime(bundle.knowledge_path), mtime(bundle.news_path))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    profile = CityProfile.from_dict(_read_json(bundle.knowledge_path))
    news = NewsCache.from_dict(_read_json(bundle.news_path))
    context = CityContext(
        slug=bundle.slug, name=profile.name or bundle.name, profile=profile, news=news
    )
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = context
    return context


def clear_cache() -> None:
    """Drop the parsed-context cache (tests, and after rebuilding knowledge)."""
    _CACHE.clear()


__all__ = ["CityContext", "clear_cache", "load_context"]
