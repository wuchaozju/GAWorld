"""Dashboard backend for 政策仿真与优化 — the research workbench's policy tab.

Reached through :mod:`gaworld.apps.research_api`, which forwards everything
under ``/api/research/policy`` here, the way it forwards the serious games.

A run is ``residents × versions + 1`` model calls, so it is a job on a
:class:`JobStore`; the finished run is written to ``output/research/policy/``
and listed from disk, so a restart loses only runs still in flight.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps.game_jobs import JobStore
from gaworld.research import policy_sim as ps

_JOBS = JobStore("policy")

#: Injected by tests; ``None`` means the configured provider via ``call_llm``.
_LLM_OVERRIDE: Callable[[str, str, str], str] | None = None

PREFIX = "/api/research/policy"


def _llm(provider: str, task: str, temperature: float, max_tokens: int) -> Callable[[str], str]:
    def call(prompt: str) -> str:
        if _LLM_OVERRIDE is not None:
            return _LLM_OVERRIDE(prompt, task, provider)
        from gaworld.llm.providers import call_llm

        return str(
            call_llm(
                prompt,
                task=f"research.policy.{task}",
                provider=provider or None,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )

    return call


def reset() -> None:
    """Drop in-memory jobs. Used by tests; production code never calls it."""
    _JOBS.reset()


def start_run(payload: dict[str, Any]) -> dict[str, Any]:
    policy = str(payload.get("policy") or "").strip()
    if not policy:
        raise ValueError("先写一段政策描述")
    provider = str(payload.get("provider") or "")
    seed = payload.get("seed")
    candidate = str(payload.get("candidate") or "")
    city = str(payload.get("city") or "")
    city_name = str(payload.get("city_name") or "")
    sample_size = int(payload.get("sample_size") or ps.DEFAULT_SAMPLE)
    seed_value = int(seed) if seed not in (None, "") else None
    verify = bool(payload.get("verify", True))

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(0.01, "正在抽样居民…")
        run = ps.run_policy_sim(
            policy=policy,
            candidate=candidate,
            city=city,
            city_name=city_name,
            sample_size=sample_size,
            seed=seed_value,
            verify=verify,
            provider=provider,
            react=_llm(provider, "react", temperature=0.8, max_tokens=500),
            optimise=_llm(provider, "optimise", temperature=0.4, max_tokens=3500),
            progress=progress,
        )
        run.update(ownership.stamp())
        ps.save_run(run)
        return {"run_id": run["id"]}

    return {"job_id": _JOBS.run(work)}


def _parts(path: str) -> list[str]:
    """``/api/research/policy/a/b`` → ``["a", "b"]``."""
    return [p for p in path[len(PREFIX) :].split("/") if p]


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    parts = _parts(path)
    if not parts:
        return {"runs": ownership.owned(ps.list_runs()), "max_sample": ps.MAX_SAMPLE, "default_sample": ps.DEFAULT_SAMPLE}, 200
    if parts[0] == "jobs" and len(parts) == 2:
        record = _JOBS.status(parts[1])
        return (record, 200) if record else ({"error": "Unknown job"}, 404)
    run = ps.load_run(parts[0])
    if run is None or not ownership.visible(run):
        return {"error": "Unknown policy run"}, 404
    if len(parts) == 1:
        return run, 200
    if len(parts) == 2 and parts[1] == "export":
        return {"filename": f"{run['id']}.md", "markdown": ps.export_markdown(run)}, 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    parts = _parts(path)
    try:
        if parts == ["run"]:
            return start_run(payload), 202
        if len(parts) == 2 and parts[1] == "delete":
            if not ownership.visible(ps.load_run(parts[0])):
                return {"error": "Unknown policy run"}, 404
            return {"deleted": ps.delete_run(parts[0]), "run_id": parts[0]}, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


__all__ = ["handle_get", "handle_post", "reset", "start_run"]
