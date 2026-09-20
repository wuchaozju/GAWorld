"""Simulation frame recording and visualizer.

Canonical home: :mod:`gaworld.apps.visualizer`.
Legacy callers should use the ``simulation_visualizer`` shim at the project root.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import UTC, datetime

from gaworld.io.avatar import ensure_agent_avatar
from gaworld.world.city_map import TERRAIN_LEGEND, project_to_tile


# Every run keeps its own copy of the trace under ``<output_dir>/runs/<run_id>``
# so the replay page can still open runs that later runs have overwritten. The
# copy lags the live trace by at most this many seconds — long enough that the
# extra I/O stays negligible next to the trace flush itself, short enough that a
# killed long run is still replayable.
ARCHIVE_INTERVAL_SECONDS = 15.0


def _utc_timestamp():
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_run_id(runs_dir):
    """A sortable, collision-free directory name for this run."""
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate, suffix = base, 2
    while os.path.exists(os.path.join(runs_dir, candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _atomic_write_json(path, payload):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def build_map_layout(city_map):
    nodes = []
    raw_nodes = city_map.get("nodes", {}) if isinstance(city_map, dict) else {}
    tile_map = city_map.get("tile_map", {}) if isinstance(city_map, dict) else {}
    bounds = city_map.get("bounds", {}) if isinstance(city_map, dict) else {}
    tile_width = int(tile_map.get("width", 160) or 160)
    tile_height = int(tile_map.get("height", 112) or 112)

    for node in raw_nodes.values():
        tile_x, tile_y = project_to_tile(
            node.get("grid_x", 0.0),
            node.get("grid_y", 0.0),
            tile_map.get("bounds", bounds or {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0}),
            tile_width,
            tile_height,
        )
        nodes.append({
            "id": node.get("id", node.get("name", "")),
            "label": node.get("label", node.get("name", "")),
            "kind": node.get("kind", "place"),
            "district": node.get("district", ""),
            "category": node.get("category", "mixed"),
            "grid_x": node.get("grid_x", 0.0),
            "grid_y": node.get("grid_y", 0.0),
            "lat": node.get("lat", 0.0),
            "lng": node.get("lng", 0.0),
            "x_km": node.get("x_km", 0.0),
            "y_km": node.get("y_km", 0.0),
            "tile_x": int(tile_x),
            "tile_y": int(tile_y),
            "style": node.get("style", {}),
            "capacity": node.get("capacity"),
            "popularity": node.get("popularity"),
            "density": node.get("density"),
        })

    return {
        "nodes": nodes,
        "edges": city_map.get("edges", []) if isinstance(city_map, dict) else [],
        "tile_map": tile_map,
        "metro_lines": city_map.get("metro_lines", []) if isinstance(city_map, dict) else [],
        "river": city_map.get("river", {}) if isinstance(city_map, dict) else {},
        "bridges": city_map.get("bridges", []) if isinstance(city_map, dict) else [],
        "bounds": bounds,
        "scale": city_map.get("scale", {}),
        "terrain_legend": TERRAIN_LEGEND,
    }


class SimulationVisualizer:
    def __init__(self, output_dir, city_map, agents, sim_meta=None, flush_every_frames=24):
        self.output_dir = output_dir
        self.trace_path = os.path.join(output_dir, "simulation_trace.json")
        self.latest_frame_path = os.path.join(output_dir, "latest_frame.json")
        self.avatar_dir = os.path.join(output_dir, "avatars")
        self.flush_every_frames = max(0, int(flush_every_frames or 0))
        self.runs_dir = os.path.join(output_dir, "runs")
        self.run_id = _new_run_id(self.runs_dir)
        self.archive_path = os.path.join(self.runs_dir, self.run_id, "simulation_trace.json")
        self._last_archive = 0.0
        layout = build_map_layout(city_map)
        trace_agents = []
        self.agent_avatar_map = {}
        for agent in agents:
            agent_id = int(agent.get("id", 0) or 0)
            avatar_path = os.path.join("avatars", f"agent_{agent_id}.svg")
            ensure_agent_avatar(agent, self.avatar_dir, filename=f"agent_{agent_id}.svg")
            self.agent_avatar_map[agent_id] = avatar_path
            agent["avatar_path"] = avatar_path
            trace_agents.append(
                {
                    "id": agent_id,
                    "name": agent.get("name", str(agent.get("id", "agent"))),
                    "home": agent.get("locations", {}).get("home", ""),
                    "workplace": agent.get("locations", {}).get("workplace", ""),
                    "avatar_path": avatar_path,
                }
            )
        self.trace = {
            "meta": {
                "generated_at": _utc_timestamp(),
                "last_updated": _utc_timestamp(),
                "finished": False,
                "frame_count": 0,
                "run_id": self.run_id,
                "sim_meta": sim_meta or {},
            },
            "map": layout,
            "agents": trace_agents,
            "frames": [],
        }
        self._write_trace()
        self._archive_trace(force=True)   # list the run before it has any frames
        self._write_latest_frame()

    def _refresh_meta(self):
        self.trace["meta"]["last_updated"] = _utc_timestamp()
        self.trace["meta"]["frame_count"] = len(self.trace.get("frames", []))

    def _write_trace(self):
        self._refresh_meta()
        _atomic_write_json(self.trace_path, self.trace)
        self._last_trace_flush = time.monotonic()
        self._archive_trace()

    def _archive_trace(self, force=False):
        """Copy the flushed trace into this run's archive directory."""
        now = time.monotonic()
        if not force and now - self._last_archive < ARCHIVE_INTERVAL_SECONDS:
            return
        try:
            os.makedirs(os.path.dirname(self.archive_path), exist_ok=True)
            tmp_path = self.archive_path + ".tmp"
            shutil.copyfile(self.trace_path, tmp_path)
            os.replace(tmp_path, self.archive_path)
            self._last_archive = now
        except OSError:
            # Archiving is best-effort: a full disk must not kill the run.
            pass

    def _write_latest_frame(self):
        self._refresh_meta()
        last_frame = self.trace["frames"][-1] if self.trace.get("frames") else {}
        _atomic_write_json(
            self.latest_frame_path,
            {
                "meta": self.trace["meta"],
                "frame": last_frame,
            },
        )

    def record_frame(self, day, time_str, day_context, env_context, env_events, agent_steps, policy=None):
        frame = {
            "index": len(self.trace["frames"]),
            "day": int(day),
            "time": str(time_str),
            "date": day_context.get("sim_date", ""),
            "weekday": day_context.get("weekday_zh", ""),
            "day_type": day_context.get("day_type_zh", ""),
            "env_context": str(env_context or "").strip(),
            "env_events": env_events if isinstance(env_events, list) else [],
            "policy": policy or {},
            "agents": agent_steps,
        }
        self.trace["frames"].append(frame)
        self._write_latest_frame()
        # Flush the full trace on the frame cadence OR every few wall-clock
        # seconds, so live dashboards (and killed runs) still see frames.
        due_by_count = self.flush_every_frames and len(self.trace["frames"]) % self.flush_every_frames == 0
        due_by_time = time.monotonic() - getattr(self, "_last_trace_flush", 0.0) >= 2.0
        if due_by_count or due_by_time:
            self._write_trace()

    def finalize(self):
        self.trace["meta"]["finished"] = True
        self._write_trace()
        self._archive_trace(force=True)
        self._write_latest_frame()



def build_agent_step_payload(agent, time_str, location, resolved_location, target_location, scheduled_activity,
                             activity, action, outcome, perception, plan, reflection, changed=False,
                             change_reason="", travel=None):
    state = {}
    for key, value in (agent.get("state", {}) or {}).items():
        if isinstance(value, (int, float)):
            state[key] = round(float(value), 4)
    return {
        "agent_id": int(agent.get("id", 0) or 0),
        "name": agent.get("name", str(agent.get("id", "agent"))),
        "avatar_path": str(agent.get("avatar_path", "") or ""),
        "time": str(time_str),
        "location": str(location or ""),
        "resolved_location": str(resolved_location or ""),
        "target_location": str(target_location or ""),
        "home": agent.get("locations", {}).get("home", ""),
        "workplace": agent.get("locations", {}).get("workplace", ""),
        "scheduled_activity": str(scheduled_activity or ""),
        "activity": str(activity or ""),
        "action": str(action or ""),
        "outcome": str(outcome or ""),
        "perception": str(perception or "").strip(),
        "plan": str(plan or "").strip(),
        "reflection": str(reflection or "").strip(),
        "changed": bool(changed),
        "change_reason": str(change_reason or "").strip(),
        "state": state,
        "travel": travel or {},
    }
