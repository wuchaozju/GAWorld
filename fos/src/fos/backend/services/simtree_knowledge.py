"""Knowledge update helpers for cached SimTree records."""

from __future__ import annotations

from fos.backend.services.simtree_registry_lifecycle import SimTreeRecord


def update_agent_knowledge(record: SimTreeRecord, agent_config: dict) -> bool:
    """Merge agent knowledge bases and documents across all nodes in a tree."""
    agents_config = agent_config.get("agents", [])
    kb_by_name = {}
    docs_by_name = {}
    for agent_cfg in agents_config:
        name = agent_cfg.get("name", "")
        if "knowledgeBase" in agent_cfg:
            kb_by_name[name] = agent_cfg["knowledgeBase"]
        if "documents" in agent_cfg:
            docs_by_name[name] = agent_cfg["documents"]

    tree = record.tree
    for node_data in tree.nodes.values():
        sim = node_data.get("sim")
        if sim is None:
            continue
        agent_map = getattr(sim, "agents", {}) or {}
        if not agent_map and hasattr(sim, "_scene_agent_map"):
            agent_map = sim._scene_agent_map()
        for agent_name, agent in agent_map.items():
            if agent_name in kb_by_name:
                agent.knowledge_base = list(kb_by_name[agent_name])
            if agent_name in docs_by_name:
                agent.documents = dict(docs_by_name[agent_name])
        scene = getattr(sim, "scene", None)
        config_agents = getattr(getattr(scene, "config", None), "agents", None)
        if isinstance(config_agents, list):
            for agent_cfg in config_agents:
                agent_name = str(agent_cfg.get("name", "")).strip()
                if agent_name in kb_by_name:
                    agent_cfg["knowledgeBase"] = list(kb_by_name[agent_name])
                if agent_name in docs_by_name:
                    agent_cfg["documents"] = dict(docs_by_name[agent_name])

    return True


def update_global_knowledge(record: SimTreeRecord, global_knowledge: dict) -> bool:
    """Update global knowledge references across all nodes in a tree."""
    tree = record.tree
    for node_data in tree.nodes.values():
        sim = node_data.get("sim")
        if sim is None:
            continue
        scene = getattr(sim, "scene", None)
        if scene is not None and hasattr(scene, "global_knowledge"):
            scene.global_knowledge = dict(global_knowledge)
            if hasattr(scene, "config"):
                scene.config.global_knowledge = dict(global_knowledge)
        for agent in (getattr(sim, "agents", {}) or {}).values():
            if hasattr(agent, "set_global_knowledge"):
                agent.set_global_knowledge(global_knowledge)

    return True
