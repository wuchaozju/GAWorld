"""Episode, habit, intention and relationship persistence for agents.

Canonical home: :mod:`gaworld.memory.experience`.
Legacy callers should use the ``experience_store`` shim at the project root.
"""

from __future__ import annotations

import json
import os

from gaworld.settings import CONFIG


def _memory_dir(cfg=None):
    base = cfg if isinstance(cfg, dict) else CONFIG
    return base.get("memory_dir", "output/memory")


def _episodes_path(agent_id, cfg=None):
    return os.path.join(_memory_dir(cfg), f"agent_{agent_id}_episodes.jsonl")


def _habits_path(agent_id, cfg=None):
    return os.path.join(_memory_dir(cfg), f"agent_{agent_id}_habits.json")


def _intentions_path(agent_id, cfg=None):
    return os.path.join(_memory_dir(cfg), f"agent_{agent_id}_intentions.json")


def _relationships_path(agent_id, cfg=None):
    return os.path.join(_memory_dir(cfg), f"agent_{agent_id}_relationships.json")


def _env_preferences_path(agent_id, cfg=None):
    return os.path.join(_memory_dir(cfg), f"agent_{agent_id}_env_preferences.json")


def _load_json_dict(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json_dict(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_agent_episodes(agent_id, cfg=None):
    path = _episodes_path(agent_id, cfg=cfg)
    if not os.path.exists(path):
        return []
    episodes = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    episodes.append(item)
    except OSError:
        return []
    return episodes


def append_agent_episode(agent_id, episode, cfg=None):
    if not isinstance(episode, dict):
        return
    path = _episodes_path(agent_id, cfg=cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(episode, ensure_ascii=False) + "\n")
    except OSError:
        return


def prune_and_decay_episodes(agent_id, cfg):
    if not isinstance(cfg, dict):
        cfg = {}
    episodes = load_agent_episodes(agent_id)
    if not episodes:
        return
    max_episodes = int(cfg.get("max_episodes_per_agent", 2000))
    current_day = int(cfg.get("current_day", 0))
    half_life = int(cfg.get("decay_half_life_days", 14))
    day_episodes = []
    older = []
    for ep in episodes:
        created_day = int(ep.get("created_at_day", ep.get("day", 0) or 0))
        age = max(0, current_day - created_day)
        if half_life > 0:
            factor = 0.5 ** (age / half_life)
        else:
            factor = 1.0
        salience = float(ep.get("salience", 0.0))
        ep["decayed_salience"] = max(0.0, min(1.0, salience * factor))
        if created_day == current_day:
            day_episodes.append(ep)
        else:
            older.append(ep)
    if len(episodes) > max_episodes:
        # Keep all current-day episodes even if they exceed max.
        keep_quota = max(0, max_episodes - len(day_episodes))
        older_sorted = sorted(
            older,
            key=lambda x: (
                float(x.get("decayed_salience", 0.0)),
                int(x.get("created_at_day", x.get("day", 0) or 0)),
            ),
            reverse=True,
        )
        kept = day_episodes + older_sorted[:keep_quota]
    else:
        kept = day_episodes + older
    kept.sort(
        key=lambda x: (
            int(x.get("day", 0) or 0),
            str(x.get("time", "")),
            str(x.get("episode_id", "")),
        )
    )
    path = _episodes_path(agent_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in kept:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def load_agent_habits(agent_id, cfg=None):
    return _load_json_dict(_habits_path(agent_id, cfg=cfg))


def save_agent_habits(agent_id, habits, cfg=None):
    if not isinstance(habits, dict):
        habits = {}
    _save_json_dict(_habits_path(agent_id, cfg=cfg), habits)


def load_agent_intentions(agent_id, cfg=None):
    return _load_json_dict(_intentions_path(agent_id, cfg=cfg))


def save_agent_intentions(agent_id, intentions, cfg=None):
    if not isinstance(intentions, dict):
        intentions = {}
    _save_json_dict(_intentions_path(agent_id, cfg=cfg), intentions)


def load_agent_relationships(agent_id, cfg=None):
    return _load_json_dict(_relationships_path(agent_id, cfg=cfg))


def save_agent_relationships(agent_id, relationships, cfg=None):
    if not isinstance(relationships, dict):
        relationships = {}
    _save_json_dict(_relationships_path(agent_id, cfg=cfg), relationships)


def load_agent_env_preferences(agent_id, cfg=None):
    """Load the agent's learned location-aversion preferences (P4)."""
    return _load_json_dict(_env_preferences_path(agent_id, cfg=cfg))


def save_agent_env_preferences(agent_id, env_preferences, cfg=None):
    """Persist the agent's learned location-aversion preferences (P4)."""
    if not isinstance(env_preferences, dict):
        env_preferences = {}
    _save_json_dict(_env_preferences_path(agent_id, cfg=cfg), env_preferences)
