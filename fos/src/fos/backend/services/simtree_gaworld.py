"""GAWorld-specific helpers for SimTree runtime construction."""

from __future__ import annotations

import os
import re


def resolve_gaworld_path(startup_path: str | None) -> str | None:
    """Resolve GAWorld path from the startup snapshot, then the live env."""
    return startup_path or os.environ.get("GAWORLD_PATH")


def _looks_like_generated_placeholder_agent(agent: dict) -> bool:
    raw_name = str(agent.get("name") or "").strip()
    if not raw_name:
        return True
    if agent.get("id"):
        return False
    numbered_name = re.fullmatch(
        r"(Agent|代理|智能体|角色)\s*#?\s*\d+", raw_name, re.IGNORECASE
    )
    generic_profile = str(
        agent.get("profile") or agent.get("role") or agent.get("role_prompt") or ""
    ).strip()
    empty_properties = not bool(agent.get("properties") or {})
    return bool(numbered_name and empty_properties and not generic_profile)


def should_use_gaworld_profile_agents(agents: list[dict]) -> bool:
    """Return True when GAWorld should replace missing or placeholder agents."""
    if not agents:
        return True
    if all(not agent.get("id") for agent in agents):
        return True
    return all(_looks_like_generated_placeholder_agent(agent) for agent in agents)


def resolve_gaworld_agents(agent_config: dict) -> list[dict]:
    """Return GAWorld profile agents when request agents are not meaningful."""
    agents = list(agent_config.get("agents") or [])
    if not agents:
        from fos.core.experiment.scenes.gaworld import profiles as profiles_module

        return profiles_module.profiles_to_fos_agents(profiles_module.load_profiles())

    if not should_use_gaworld_profile_agents(agents):
        return agents

    from fos.core.experiment.scenes.gaworld import profiles as profiles_module

    profile_agents = profiles_module.profiles_to_fos_agents(
        profiles_module.load_profiles()
    )
    if not profile_agents:
        return agents

    requested_count = len(agents)
    if requested_count < len(profile_agents):
        profile_agents = profile_agents[:requested_count]

    return profile_agents


def resolve_gaworld_agent_ids(params: dict, agents: list[dict]) -> list[str]:
    """Build the GAWorld agent ID list from params first, then explicit agents."""
    raw_agent_ids = params.get("agent_ids", [])
    if isinstance(raw_agent_ids, str):
        ids = [part.strip() for part in raw_agent_ids.split(",") if part.strip()]
        if ids:
            return ids
    elif isinstance(raw_agent_ids, list):
        ids = [
            str(agent_id).strip() for agent_id in raw_agent_ids if str(agent_id).strip()
        ]
        if ids:
            return ids

    resolved_ids: list[str] = []
    for agent in agents:
        raw_agent_id = agent.get("id")
        if raw_agent_id is None:
            continue
        agent_id = str(raw_agent_id).strip()
        if agent_id:
            resolved_ids.append(agent_id)
    return resolved_ids


# ---------------------------------------------------------------------------
# Phase 6 — checkpoint fork / recovery runtime support
# ---------------------------------------------------------------------------


def branch_runtime_overrides(
    branch_dir: str,
    checkpoint_ref: dict | None = None,
    interventions_path: str | None = None,
    agent_llm_map: dict | None = None,
    default_provider: str | None = None,
) -> dict:
    """Runtime config patch isolating ONE branch of a forked GAWorld run.

    Every GAWorld writable path is redirected under ``branch_dir`` using the
    authoritative ``gaworld.city.config.run_root_overrides`` key set (the same
    semantics as ``gaworld/parallel/spec.py::world_overrides``), plus:

    - ``gaworld.checkpoint.restore_dir`` — where THIS branch writes its own
      new checkpoints (never the source run's checkpoint directory);
    - ``kernel.interventions_path`` — the branch's intervention queue, so a
      branch intervention is audited only in that branch (optionally pointed
      at an explicit ``interventions_path``);
    - ``llm.routing`` — per-branch LLM routing: explicit ``agent_llm_map``
      entries (exact int GAWorld agent IDs, JSON string keys) land in
      ``llm.routing.agents``; unassigned agents follow ``llm.routing.default``,
      which defaults to the branch's own provider identity so the two sides of
      a fork can be told apart at runtime. Pass ``default_provider`` to pin it.

    Provenance (checkpoint references, recovery history) deliberately lives in
    ``node.meta``, never here — this patch is runtime config only.
    """
    from gaworld.city.config import run_root_overrides

    base = str(branch_dir).rstrip("/")
    patch: dict = run_root_overrides(base)

    # The branch writes its OWN checkpoints under its own dir; forks restore
    # from the SOURCE checkpoint's run dir, never write into it.
    patch.setdefault("gaworld", {}).setdefault("checkpoint", {})[
        "restore_dir"
    ] = f"{base}/checkpoints"

    if interventions_path:
        patch.setdefault("kernel", {})[
            "interventions_path"
        ] = str(interventions_path)

    if default_provider is None:
        name = re.sub(r"[^A-Za-z0-9_-]", "-", base.rsplit("/", 1)[-1] or base)
        default_provider = re.sub(r"^branch[-_]", "", name) or name

    agents: dict[str, dict] = {}
    for agent_id, entry in (agent_llm_map or {}).items():
        # Exact int GAWorld IDs, keyed the way resolve_llm_target reads them.
        agents[str(int(agent_id))] = dict(entry)
    patch.setdefault("llm", {})["routing"] = {
        "default": {"provider": str(default_provider), "model": None},
        "agents": agents,
    }
    return patch


RECOVERY_ACTIONS = ("retry", "fix_and_retry", "substitute")


def prepare_recovery(
    node: dict,
    action: str,
    runtime_config: dict | None = None,
    agent_id: int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Build the recovery plan for a failed node — Retry / Fix-and-retry /
    Substitute ONLY.

    Every action restores the LAST COMPLETED checkpoint referenced by the
    node (never partially mutated state) into a FRESH attempt directory; the
    failed attempt's evidence is retained. ``substitute`` requires an explicit
    ``provider`` AND ``model`` for the one affected agent — no auto-substitution.
    ``resume_partial_day`` (or any other action) raises ValueError.
    """
    from fos.i18n import T

    if action not in RECOVERY_ACTIONS:
        raise ValueError(
            T("simtree_gaworld.unknown_action", action=repr(action), allowed=str(RECOVERY_ACTIONS))
        )
    meta = node.get("meta") or {}
    ref = meta.get("checkpoint")
    if not ref:
        raise ValueError(T("simtree_gaworld.no_checkpoint_ref"))
    ref = _jsonclone(ref)
    if action == "substitute" and (provider is None or model is None):
        raise TypeError(T("simtree_gaworld.substitute_required"))

    branch = str(meta.get("branch") or f"node-{node.get('id')}")
    failed_day = meta.get("failed_day")
    if failed_day is None:
        failed_day = int(ref.get("day") or 0) + 1

    previous = meta.get("attempt_dir")
    if previous:
        match = re.search(r"attempt_(\d+)$", str(previous))
        attempt_number = int(match.group(1)) + 1 if match else 2
        attempt_dir = re.sub(r"attempt_\d+$", f"attempt_{attempt_number}", str(previous))
    else:
        attempt_number = 1
        day = int(ref.get("day") or 0)
        attempt_dir = f"{branch}/attempts/day_{day:04d}_attempt_{attempt_number}"

    replacement = None
    if action == "substitute":
        replacement = {
            "agent_id": int(agent_id) if agent_id is not None else None,
            "provider": str(provider),
            "model": str(model),
        }

    return {
        "action": action,
        "branch": branch,
        "failed_day": failed_day,
        "agent_id": agent_id if action == "substitute" else meta.get("agent_id"),
        "provider": str(provider) if provider is not None else None,
        "model": str(model) if model is not None else None,
        "original_provider": meta.get("runtime_provider"),
        "original_model": meta.get("runtime_model"),
        "failure": meta.get("runtime_error"),
        "replacement": replacement,
        "checkpoint": ref,
        "checkpoint_restored": ref,
        "attempt_dir": attempt_dir,
        "attempt_number": attempt_number,
        "runtime_config": runtime_config if runtime_config is not None else meta.get("runtime_config"),
    }


def record_recovery(node: dict, action: str, attempt_dir: str) -> dict:
    """Record on the node which recovery action was taken (frontend-facing
    shape, serialization-safe)."""
    meta = node.setdefault("meta", {})
    meta["runtime_status"] = "recovering"
    meta["recovery"] = {
        "action": action,
        "attempt_dir": str(attempt_dir),
    }
    node.setdefault("logs", []).append(
        {"event": "recovery", "action": action, "attempt_dir": str(attempt_dir)}
    )
    return meta["recovery"]


def validate_checkpoint_reference(ref: dict, expected_run_id: str | None = None) -> bool:
    """Fail LOUDLY on a missing/corrupt/foreign checkpoint reference.

    No hidden fallback: a reference that cannot be proven valid raises
    ValueError. Validation is launch-time; ``SimTree.fork_from_checkpoint``
    records references without touching the filesystem.
    """
    import json
    from pathlib import Path

    from fos.i18n import T

    if not isinstance(ref, dict):
        raise ValueError(T("simtree_gaworld.ref_not_dict"))
    path = Path(str(ref.get("checkpoint_path") or ""))
    if not path.is_dir():
        raise ValueError(T("simtree_gaworld.dir_missing", path=str(path)))
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(T("simtree_gaworld.manifest_missing", path=str(manifest_path)))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            T("simtree_gaworld.manifest_corrupt", path=str(manifest_path), detail=exc)
        ) from exc
    if expected_run_id is not None and str(manifest.get("run_id")) != str(expected_run_id):
        raise ValueError(
            T(
                "simtree_gaworld.lineage_mismatch",
                found=manifest.get("run_id"),
                expected=expected_run_id,
            )
        )
    day = ref.get("day")
    if day is not None and int(manifest.get("completed_day", -1)) != int(day):
        raise ValueError(
            T(
                "simtree_gaworld.day_mismatch",
                path=str(path),
                found=manifest.get("completed_day"),
                day=day,
            )
        )
    expected_sha = ref.get("manifest_sha")
    manifest_sha = manifest.get("manifest_sha")
    if expected_sha and manifest_sha and str(expected_sha) != str(manifest_sha):
        raise ValueError(T("simtree_gaworld.sha_mismatch", path=str(path)))
    return True


def _jsonclone(value):
    import json

    return json.loads(json.dumps(value))
