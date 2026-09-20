"""Standard runtime interventions (K5).

Domain-free interventions every simulation gets out of the box, registered
by :func:`gaworld.kernel.context.build_kernel`. Every ``intervene`` call is
audited to the ``controller.intervention`` record table.

- ``set_agent_state``: write one value into an agent's state dict (the nine
  normalized state variables are kernel assets). Immediate.
- ``update_config``: set a dotted-path value in the live CONFIG dict.
  Immediate; consumers that snapshot config at setup won't see it until the
  next run — same caveat as dashboard overrides.
- ``remove_agent``: queue an agent for removal; the main loop applies the
  queue at the next day boundary (mid-tick removal would corrupt the step
  pipeline). The loop also scrubs the removed ids from every remaining
  agent's ``social_neighbors`` so social stages don't dangle.

``add_agent`` is not implemented yet: mid-run agent creation needs a seed
ingestion path (profile + state row + social roster + memory bootstrap) —
tracked in the migration proposal as follow-up work.
"""

from __future__ import annotations


def _set_agent_state(ctx, agent_id=None, key=None, value=None):
    agent = ctx.agents_by_id.get(agent_id)
    if agent is None:
        try:
            agent = ctx.agents_by_id.get(int(agent_id))
        except (TypeError, ValueError):
            agent = None
    if agent is None:
        raise ValueError(f"unknown agent {agent_id!r}")
    if not key:
        raise ValueError("set_agent_state requires `key`")
    agent.setdefault("state", {})[str(key)] = float(value)
    return {"agent_id": agent.get("id"), "key": str(key), "value": float(value)}


def _update_config(ctx, path="", value=None):
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        raise ValueError("update_config requires a dotted `path`")
    node = ctx.config
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value
    return {"path": ".".join(parts), "value": value}


def _remove_agent(ctx, agent_id=None):
    if agent_id is None:
        raise ValueError("remove_agent requires `agent_id`")
    queue = ctx.plugin_state("population").setdefault("remove", [])
    queue.append(int(agent_id))
    return {"queued": int(agent_id), "applies": "next day start"}


def register_standard_interventions(ctx) -> None:
    ctx.controller.register_intervention("set_agent_state", _set_agent_state)
    ctx.controller.register_intervention("update_config", _update_config)
    ctx.controller.register_intervention("remove_agent", _remove_agent)
