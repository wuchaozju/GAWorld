"""Runtime external-info absorption.

D3 of the RAG enhancement plan. The init-time bootstrap in
``gaworld.sim._rag`` seeds an agent with background knowledge once;
this module extends that flow into the running simulation so each
agent's RAG slowly absorbs *fresh* external information aimed at
their current interests / values / pressures.

The orchestrator is pure: callers inject a ``web_fetch_fn`` (an item
producer) and an ``llm`` callable. This keeps the unit tests offline
and lets the day-tick hook in ``generative_city_sim.py`` plug in
whichever web/search infra the simulation is already using.

``web_fetch_fn(query: str) -> list[dict]`` is expected to return any
number of items shaped like::

    {"title": "...", "content": "...", "url": "https://..."}

(Empty/None values are tolerated.) Each item gets summarised via the
existing ``_summarize_bootstrap_web_item`` helper so the final stored
text matches the format ``_external_rag_hint`` already knows how to
read.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gaworld.settings import CONFIG
from gaworld.logging_setup import get_logger
from gaworld.memory.store import vector_db_add_entry

_LOG = get_logger("gaworld.memory.ingest")


def _ingest_config() -> dict[str, Any]:
    return (CONFIG.get("external_rag", {}) or {})


def derive_absorb_queries(agent: dict[str, Any], *, max_queries: int = 2) -> list[str]:
    """Return up to ``max_queries`` topic strings to feed to a search API.

    Topics are derived from the agent's growth focus first (because
    that is what the simulator has been actively cultivating), then
    fall back to declared values + role + a stress/economy hint. The
    queries are short — one to three terms — and intentionally generic
    so the simulator can hand them off to any kind of web search.
    """
    if not isinstance(agent, dict):
        return []
    candidates: list[str] = []

    # 1) Growth focus first — these are the topics the agent is
    # actively practicing or improving on.
    profile = agent.get("growth_profile")
    if profile:
        try:
            from gaworld.interests import growth_focus
            for focus in growth_focus(profile, limit=max_queries):
                if focus and focus not in candidates:
                    candidates.append(focus)
        except Exception:  # pragma: no cover - growth optional
            pass

    # 2) Job + an emotional / economic colour to make the query
    # concrete enough to retrieve something the agent might care about.
    job = str(agent.get("job", "")).strip()
    state = agent.get("state", {}) if isinstance(agent.get("state", {}), dict) else {}
    stress = float(state.get("stress", 0.5) or 0.5)
    econ = float(state.get("econ_security", 0.5) or 0.5)
    if job and len(candidates) < max_queries:
        if stress >= 0.6 or econ <= 0.45:
            candidates.append(f"{job} 行业 压力")
        else:
            candidates.append(f"{job} 行业 动态")

    # 3) Values, last resort.
    values = str(agent.get("values", "")).strip()
    if values and len(candidates) < max_queries:
        # Take a short slice — search APIs prefer 2-6 token queries.
        candidates.append(values[:30])

    return candidates[: max(0, int(max_queries))]


def absorb_external_for_agent(
    agent: dict[str, Any],
    *,
    day: int | None,
    time_str: str | None,
    llm: Callable[[str], str],
    web_fetch_fn: Callable[[str], list[dict[str, Any]]],
    max_queries: int | None = None,
    max_items_per_query: int = 1,
) -> list[str]:
    """Pull and store fresh external snippets for ``agent``.

    Returns the list of summary strings that were actually written to
    the vector DB (one per accepted item). Honors
    ``external_rag.runtime_absorb`` (off by default) and the daily
    quota set in config; callers don't need to gate themselves.

    All failures degrade quietly: a flaky ``web_fetch_fn`` or LLM
    raising will result in fewer (or zero) ingests, never a sim-loop
    crash. This is critical because the planned caller is a day-tick
    hook running for every agent.
    """
    cfg = _ingest_config()
    if not cfg.get("runtime_absorb", False):
        return []
    if not isinstance(agent, dict):
        return []
    agent_id = int(agent.get("id", 0) or 0)
    if not agent_id:
        return []

    quota = int(cfg.get("daily_quota_per_agent", 1))
    if quota <= 0:
        return []
    queries = derive_absorb_queries(
        agent,
        max_queries=int(max_queries if max_queries is not None else quota),
    )
    if not queries:
        return []

    # Late import — avoids circular: _rag imports memory.store, and
    # this module sits in memory.* too.
    try:
        from gaworld.sim._rag import _summarize_bootstrap_web_item
    except Exception as exc:  # pragma: no cover
        _LOG.warning("ingest: cannot import summariser: %s", exc)
        return []

    written: list[str] = []
    remaining = quota
    for query in queries:
        if remaining <= 0:
            break
        try:
            items = web_fetch_fn(query) or []
        except Exception as exc:
            _LOG.debug("ingest: fetch failed for %s: %s", query, exc)
            continue
        for item in items[: max(1, int(max_items_per_query))]:
            if remaining <= 0:
                break
            title = str((item or {}).get("title", "")).strip()
            content = str((item or {}).get("content", "")).strip()
            url = str((item or {}).get("url", "")).strip()
            if not content and not title:
                continue
            try:
                summary = _summarize_bootstrap_web_item(
                    agent, title, content, url
                )
            except Exception as exc:
                _LOG.debug("ingest: summariser failed for %s: %s", url or title, exc)
                continue
            if not summary:
                continue
            payload = f"[额外信息·D{day}] {summary}".strip() if day is not None else f"[额外信息] {summary}"
            vector_db_add_entry(
                agent_id,
                "external_info",
                payload,
                sim_day=day,
                sim_time=time_str or "absorb",
                # Fresh real-world info is mildly salient by default; the
                # consolidation/decay system will adjust over time.
                salience=0.65,
            )
            written.append(payload)
            remaining -= 1
    if written:
        _LOG.info("absorbed %d external snippets for agent %s", len(written), agent_id)
    return written


__all__ = [
    "absorb_external_for_agent",
    "derive_absorb_queries",
]
