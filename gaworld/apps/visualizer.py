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

#: How often the live frame (the tick in progress) is flushed to disk. One
#: write per resident would be heavy on a big cast; the tick's own write
#: publishes the finished frame regardless.
LIVE_FRAME_WRITE_INTERVAL = 0.5


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
        nodes.append(
            {
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
            }
        )

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
        # A frame the dashboard may read before it lands in the trace: the
        # residents' start positions, then the tick that is still running.
        self._live_frame = None
        self._last_live_write = 0.0
        self.live_write_interval = LIVE_FRAME_WRITE_INTERVAL
        self._write_trace()
        self._archive_trace(force=True)  # list the run before it has any frames
        self._publish_initial_frame(agents)
        self._write_latest_frame()

    def _publish_initial_frame(self, agents):
        """Publish where everyone stands before the first tick runs.

        The first *recorded* frame only lands once a whole tick finished --
        one model call per resident, so minutes. Until then the dashboard's
        map showed an empty city and the indoor view was blank, which read
        as a broken run. The residents' start positions are known here, so
        publish them right away: the map fills with avatars immediately.

        The frame is deliberately *not* part of ``trace["frames"]`` — it is a
        live preview, and the archive keeps only real frames.
        """
        steps = []
        for agent in agents:
            locations = agent.get("locations") or {}
            current = locations.get("current") or locations.get("home") or ""
            steps.append(
                build_agent_step_payload(
                    agent,
                    time_str="",
                    location=current,
                    resolved_location=current,
                    target_location=current,
                    scheduled_activity="",
                    activity="",
                    action="",
                    outcome="",
                    perception="",
                    plan="",
                    reflection="",
                )
            )
        self._live_frame = {
            "index": len(self.trace["frames"]),
            "day": 0,
            "time": "",
            "date": "",
            "weekday": "",
            "day_type": "",
            "env_context": "",
            "env_events": [],
            "policy": {},
            "phase": "init",
            "agents": steps,
        }

    def note_agent_step(self, day, time_str, payload, env_context="", env_events=None, policy=None):
        """Publish the tick in progress, one resident at a time.

        A tick costs one model call per resident, so with a handful of
        residents it takes minutes and the dashboard showed nothing until all
        of them were done. Report each resident as it lands: the map fills
        in progressively, and residents that have not reported yet keep the
        place they had in the previous frame.

        The live frame occupies the slot the finished tick will take, so the
        dashboard's "latest frame" and the trace agree on the index.
        """
        slot = len(self.trace["frames"])
        day = int(day or 0)
        time_str = str(time_str or "")
        live = self._live_frame
        seed = []
        if live is not None and int(live.get("index", -1)) == slot:
            if live.get("phase") == "init":
                # The start-positions preview becomes the seed of this tick.
                seed = [dict(step) for step in live.get("agents") or []]
                live = None
            elif (int(live.get("day", 0)), str(live.get("time", ""))) == (day, time_str):
                seed = live.get("agents") or []  # same tick, keep accumulating
        if live is None:
            if not seed:
                previous = self.trace["frames"][-1].get("agents") if self.trace["frames"] else []
                seed = [dict(step) for step in (previous or [])]
            live = {
                "index": slot,
                "day": day,
                "time": time_str,
                "date": "",
                "weekday": "",
                "day_type": "",
                "env_context": "",
                "env_events": [],
                "policy": {},
                "phase": "live",
                # Seed with the previous frame: a resident that has not
                # reported yet stays where they were instead of vanishing.
                "agents": seed,
            }
            self._live_frame = live
            # A new tick starts: publish its first resident right away
            # instead of waiting out the write interval.
            self._last_live_write = 0.0
        live["day"] = day
        live["time"] = time_str
        live["env_context"] = str(env_context or "")
        live["env_events"] = list(env_events or [])
        live["policy"] = policy or {}
        steps = live["agents"]
        agent_id = int(payload.get("agent_id", 0) or 0)
        for index, step in enumerate(steps):
            if int(step.get("agent_id", 0) or 0) == agent_id:
                steps[index] = payload
                break
        else:
            steps.append(payload)
        # One write per resident would be a lot of I/O on a big cast; the
        # tick's own write at the end publishes the complete frame anyway.
        now = time.monotonic()
        if now - self._last_live_write >= self.live_write_interval:
            self._last_live_write = now
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
        # The live frame wins over the last recorded one: it is what the
        # dashboard should show right now (the start positions, or the tick
        # that is still running).
        live = self._live_frame
        if live is not None:
            last_frame = live
        else:
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
        # The tick is complete: the live preview hands over to the real frame.
        self._live_frame = None
        self._last_live_write = 0.0
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


def build_agent_step_payload(
    agent,
    time_str,
    location,
    resolved_location,
    target_location,
    scheduled_activity,
    activity,
    action,
    outcome,
    perception,
    plan,
    reflection,
    changed=False,
    change_reason="",
    travel=None,
):
    state = {}
    for key, value in (agent.get("state", {}) or {}).items():
        if isinstance(value, (int, float)):
            state[key] = round(float(value), 4)
    payload = {
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
    # The room the resident stands in (``local_physical.rooms``); the indoor
    # views seat them there instead of guessing from the activity.
    locations = agent.get("locations") or {}
    room = locations.get("room")
    if (
        isinstance(room, dict)
        and not locations.get("in_transit")
        and room.get("node") == locations.get("current")
    ):
        payload["room"] = {k: room.get(k) or "" for k in ("node", "unit", "arena", "object")}
    # The room inside their own home (``home`` plugin): which room they are
    # in and what they are doing there. The console's indoor mode draws the
    # resident's own flat from it.
    home_obs = agent.get("_home_observation") or {}
    if home_obs.get("is_at_home"):
        home_room = home_obs.get("current_room") or {}
        payload["home_room"] = {
            "key": home_room.get("key") or "",
            "name": home_room.get("name") or "",
            "activity": str(activity or scheduled_activity or ""),
        }
    # The household id (``family`` plugin): co-residents share one flat, so the
    # indoor view can show the family at home instead of the whole block.
    family = (agent.get("ext") or {}).get("family") or {}
    household_id = family.get("household_id") if isinstance(family, dict) else ""
    if household_id:
        payload["household"] = str(household_id)
    return payload
