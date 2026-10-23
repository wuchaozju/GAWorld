"""GAWorld-specific helpers for SimTree runtime construction."""

from __future__ import annotations

import os
import re

from fos.backend.services.gaworld_agents import GAWorldUnavailableError

#: Phase 9 single-implementation audit marker: branch_runtime_overrides
#: takes its run-path key set from the authoritative worldrun definition.
_RUN_ROOT_OVERRIDES_SOURCE = "gaworld.worldrun"


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


def _live_gaworld_population(city: str = "") -> list[dict]:
    """Fetch the LIVE GAWorld population (exact int IDs) via the gaworld_agents
    service, paging until every resident of the selected city is collected.

    GAWorld owns the residents; there is deliberately NO snapshot fallback —
    a down or empty GAWorld raises :class:`GAWorldUnavailableError` so the
    caller surfaces a typed error instead of silently substituting bundled
    snapshot data behind the user's back.
    """
    from fos.backend.services import gaworld_agents as gaworld_agents_service

    collected: list[dict] = []
    offset = 0
    while True:
        page = gaworld_agents_service.get_agents(city=city, offset=offset)
        agents = list(page.get("agents") or [])
        collected.extend(agents)
        offset += len(agents)
        if not agents or offset >= int(page.get("total") or offset):
            break
    return [gaworld_agents_service.to_fos_agent(agent) for agent in collected]


def resolve_gaworld_agents(agent_config: dict) -> list[dict]:
    """Return LIVE GAWorld agents when request agents are not meaningful.

    Placeholder or missing request agents are replaced with the live GAWorld
    population (exact int IDs) — never with a bundled snapshot. When GAWorld
    cannot answer, the typed :class:`GAWorldUnavailableError` propagates.
    """
    agents = list(agent_config.get("agents") or [])
    if agents and not should_use_gaworld_profile_agents(agents):
        return agents

    city = str(agent_config.get("city") or "").strip()
    live_agents = _live_gaworld_population(city=city)
    if not live_agents:
        raise GAWorldUnavailableError(
            "GAWorld returned no residents for the selected city; "
            "refusing to fall back to a snapshot population"
        )

    requested_count = len(agents)
    if 0 < requested_count < len(live_agents):
        live_agents = live_agents[:requested_count]

    return live_agents


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
    from gaworld.worldrun.config import run_root_overrides

    # Phase 9 single-implementation audit: the path-key set comes from the
    # authoritative gaworld.worldrun definition (same table cities, user
    # worlds and the parallel-worlds runner use).
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


# ---------------------------------------------------------------------------
# Rerun / launch runtime isolation (task 2834)
# ---------------------------------------------------------------------------


def derive_branch_dir(runs_root: str, node_id: int, run_id: int | None = None) -> str:
    """Derive the unique, node-owned run root for ONE execution attempt.

    Pure path derivation — no directory is created here. The pair
    ``(node_id, run_id)`` is enough: every rerun creates a fresh node, so
    two attempts can never share a root, and a rerun of the same run id on
    a different node still isolates.

    A relative ``runs_root`` (the default ``data/gaworld_runs``) is
    absolutized against the CURRENT process cwd — the backend that calls
    this is also the one that materializes ``kernel/interventions.json``.
    The GAWorld subprocess runs with ``cwd = gaworld_path``, so it would
    otherwise resolve the forwarded queue path against a DIFFERENT base
    directory and silently drain a file nobody wrote (review 2835,
    Finding 1). An absolute path is process-independent.
    """
    root = str(runs_root)
    if not os.path.isabs(root):
        root = os.path.abspath(root)
    base = f"node_{int(node_id)}"
    if run_id is not None:
        base += f"_run_{int(run_id)}"
    return f"{root.rstrip('/')}/{base}"


def isolate_node_runtime(
    tree,
    node_id: int,
    branch_dir: str,
    run_id: int | None = None,
    status: str = "running",
) -> dict:
    """Give ONE GAWorld-backed execution node its own writable runtime root.

    Applies the EXISTING :func:`branch_runtime_overrides` patch (no duplicate
    override keys) as a single ``config_params_patch`` op — the same deep-merge
    semantics the tree uses at branch time — and stamps runtime provenance on
    the node meta:

    - ``meta["branch_dir"]`` / ``meta["interventions_path"]``;
    - ``meta["gaworld"]`` = run_dir / checkpoint_dir / state_dir /
      interventions_path / status / run_id / node_id, so
      ``compare_branches`` and recovery can resolve the run.

    The SOURCE checkpoint stays shared/read-only; everything the attempt
    writes (run output, state history, checkpoints, kernel intervention
    queue, recorder records) is redirected under ``branch_dir``.
    """
    from fos.core.experiment.scenes.gaworld.runtime_modes import merge_nested_overrides

    base = str(branch_dir).rstrip("/")
    interventions_path = f"{base}/kernel/interventions.json"
    patch = branch_runtime_overrides(base, interventions_path=interventions_path)

    node = tree.nodes[int(node_id)]
    sim = node.get("sim")
    if sim is not None:
        config = getattr(getattr(sim, "scene", None), "config", None)
        if config is not None and hasattr(config, "parameters"):
            config.parameters = merge_nested_overrides(dict(config.parameters), patch)
    # Documented as one config_params_patch op (deep-merge) so the ops list
    # stays the single definition point of what this attempt ran with.
    node.setdefault("ops", []).append(
        {"op": "config_params_patch", "updates": patch, "runtime_isolation": True}
    )

    meta = node.setdefault("meta", {})
    meta["branch_dir"] = base
    meta["interventions_path"] = interventions_path
    gaworld_meta = dict(meta.get("gaworld") or {})
    gaworld_meta.update(
        {
            "run_dir": base,
            "checkpoint_dir": f"{base}/checkpoints",
            "state_dir": f"{base}/state",
            "interventions_path": interventions_path,
            "status": status,
            "node_id": int(node_id),
            "run_id": int(run_id) if run_id is not None else None,
        }
    )
    meta["gaworld"] = gaworld_meta
    return {"branch_dir": base, "interventions_path": interventions_path, "patch": patch}


def materialize_pending_interventions(tree, node_id: int) -> dict | None:
    """Consume ``meta["pending_interventions"]`` (checkpoint-fork text) into
    the branch's OWN kernel queue file.

    The fork dialog stores intervention text on the forked node; this turns
    it into a real entry in that node's ``kernel.interventions_path`` queue,
    so the GAWorld kernel (the authoritative runtime mechanism) consumes and
    audits it like any other queued intervention. Idempotent per attempt: a
    second materialize call never re-enqueues. Siblings are untouched — only
    the targeted node's queue file is written.
    """
    import json
    from pathlib import Path

    node = tree.nodes.get(int(node_id))
    if node is None:
        raise KeyError(f"node {node_id} not found in tree")
    meta = node.setdefault("meta", {})
    text = meta.get("pending_interventions")
    if not text or meta.get("pending_interventions_materialized"):
        return None
    interventions_path = meta.get("interventions_path")
    if not interventions_path:
        raise ValueError(
            "node has pending_interventions but no interventions_path — "
            "apply isolate_node_runtime() first"
        )
    entry = {
        "id": f"fork-{int(node_id)}-pending",
        "op": "interventions_text",
        "text": str(text),
        "source": "checkpoint_fork",
        "target_node": int(node_id),
    }
    path = Path(interventions_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"pending": [], "applied": []}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"pending": [], "applied": []}
    payload.setdefault("pending", []).append(entry)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    meta["pending_interventions_materialized"] = True
    node.setdefault("logs", []).append(
        {
            "event": "intervention_materialized",
            "node": int(node_id),
            "data": {"intervention_id": entry["id"], "queue": str(path)},
        }
    )
    return entry


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
