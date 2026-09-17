"""Twin operations: authenticate, submit, snapshot, profile, trail.

All authorization lives here so the HTTP layer stays a routing shell. Every
operation takes a bearer token and resolves the agent id from it; no operation
accepts an agent id from the caller.
"""

from __future__ import annotations

import time

import math

from gaworld.io.avatar import build_agent_avatar_svg
from gaworld.twin import binding, geo, life, places, roster, store


ACTION_TAGS = (
    "commute",
    "work",
    "study",
    "meal",
    "shopping",
    "rest",
    "social",
    "exercise",
    "errand",
    "other",
)

_UNAUTHORIZED = {"ok": False, "status": 401, "error": "invalid token"}


def _unauthorized():
    return dict(_UNAUTHORIZED)


class TwinBackend:
    """Composes geo/store/binding into the operations the server exposes."""

    def __init__(
        self,
        root=store.DEFAULT_ROOT,
        bindings_path=binding.DEFAULT_PATH,
        city_map=None,
        snapshot_ttl_minutes=30,
        max_snap_km=geo.DEFAULT_MAX_SNAP_KM,
        diary_dir=life.DEFAULT_DIARY_DIR,
        state_dir=life.DEFAULT_STATE_DIR,
        memory_dir=life.DEFAULT_MEMORY_DIR,
        city_places=None,
        roster_path="",
        simulated_ids=(),
    ):
        self.roster_path = roster_path
        self.simulated_ids = set(int(i) for i in (simulated_ids or ()))
        # Read once: naming a coordinate must never touch the network, and
        # re-reading the bundles per report would be pointless IO.
        self.city_places = (
            places.load_city_places() if city_places is None else city_places
        )
        self.root = root
        self.bindings_path = bindings_path
        self.city_map = city_map or {"nodes": {}}
        self.snapshot_ttl_minutes = float(snapshot_ttl_minutes)
        self.max_snap_km = float(max_snap_km)
        self.diary_dir = diary_dir
        self.state_dir = state_dir
        self.memory_dir = memory_dir

    # -- auth ------------------------------------------------------------

    def _agent_for(self, token):
        return binding.resolve_token(token, path=self.bindings_path)

    def _resolve(self, token):
        """``(agent_id, error)``; ``error`` is ``None`` once an agent resolves.

        A valid token that has not picked an agent yet is a 409, not a 401 —
        the phone needs to show a picker, not throw the user back to the
        invite-code screen.
        """
        status = binding.token_status(token, path=self.bindings_path)
        if not status["valid"]:
            return None, _unauthorized()
        if status["agent_id"] is None:
            return None, {"ok": False, "status": 409, "error": "no agent selected"}
        return status["agent_id"], None

    def authenticate(self, code):
        """Exchange an invite code for a bearer token."""
        token = binding.redeem_code(code, path=self.bindings_path)
        if token is None:
            return {"ok": False, "status": 403, "error": "invalid or revoked code"}
        return {
            "ok": True,
            "token": token,
            "label": binding.label_for_token(token, path=self.bindings_path),
            # None when the code was issued unbound — the phone shows the
            # agent picker instead of going straight to the main screen.
            "agent_id": binding.resolve_token(token, path=self.bindings_path),
        }

    # -- write -----------------------------------------------------------

    def _enrich(self, raw):
        """Attach server-computed geo fields and normalize client input."""
        loc = raw.get("loc") or {}
        located = geo.locate(
            loc.get("lng"),
            loc.get("lat"),
            city_map=self.city_map,
            max_snap_km=self.max_snap_km,
        )
        tag = str(raw.get("action_tag") or "other")
        return {
            "report_id": str(raw.get("report_id") or ""),
            "ts": float(raw.get("ts") or 0),
            "tz_offset": int(raw.get("tz_offset") or 0),
            "loc": {
                "lat": float(loc.get("lat") or 0),
                "lng": float(loc.get("lng") or 0),
                "acc_m": float(loc.get("acc_m") or 0),
                "source": "manual" if loc.get("source") == "manual" else "gps",
            },
            "grid": located["grid"],
            "node_id": located["node_id"],
            "snap_km": located["snap_km"],
            # `out_of_map` means "did not match a map node" — NOT "position
            # unknown". The coordinate above is always recorded, and `place`
            # names it offline so an away-from-the-city fix is still legible.
            "out_of_map": located["out_of_map"],
            "place": places.describe(
                loc.get("lat"), loc.get("lng"), city_places=self.city_places
            ),
            "action_tag": tag if tag in ACTION_TAGS else "other",
            "note": str(raw.get("note") or ""),
        }

    def submit(self, token, reports):
        """Store a batch of reports against the token's bound agent."""
        agent_id, error = self._resolve(token)
        if error:
            return error
        if not isinstance(reports, list):
            return {"ok": False, "status": 400, "error": "body must be a JSON array"}

        enriched = []
        for raw in reports:
            if not isinstance(raw, dict):
                return {"ok": False, "status": 400, "error": "each report must be an object"}
            record = self._enrich(raw)
            if not record["report_id"]:
                return {"ok": False, "status": 400, "error": "report_id is required"}
            enriched.append(record)

        result = store.append_reports(agent_id, enriched, root=self.root)
        return {
            "ok": True,
            "status": 200,
            "accepted": result["accepted"],
            "duplicates": result["duplicates"],
        }

    # -- read ------------------------------------------------------------

    def snapshot(self, token, now_ts=None):
        """Latest report plus whether it is fresh enough to mirror."""
        agent_id, error = self._resolve(token)
        if error:
            return error
        record = store.read_snapshot(agent_id, root=self.root)
        now = time.time() if now_ts is None else float(now_ts)
        return {
            "ok": True,
            "status": 200,
            "agent_id": agent_id,
            "report": record,
            "fresh": store.is_fresh(record, now, self.snapshot_ttl_minutes),
            "ttl_minutes": self.snapshot_ttl_minutes,
        }

    def profile(self, token):
        """Agent identity and avatar for the phone's header card."""
        agent_id, error = self._resolve(token)
        if error:
            return error
        label = binding.label_for_token(token, path=self.bindings_path)
        # Prefer the resident's real name over the invite label: after picking
        # 高安昊 from the roster, seeing "Agent 2" in the header is jarring.
        # The name also seeds the avatar, so this makes the face stable per
        # resident rather than per invite code.
        profile = next(
            (a for a in roster.load_roster(self.roster_path) if a["id"] == agent_id),
            None,
        )
        agent = {
            "id": agent_id,
            "name": (profile or {}).get("name") or label or f"agent_{agent_id}",
            "job": (profile or {}).get("job", ""),
            "age": (profile or {}).get("age", ""),
        }
        label = agent["name"]
        return {
            "ok": True,
            "status": 200,
            "agent_id": agent_id,
            "label": label,
            "avatar_svg": build_agent_avatar_svg(agent, size=128),
            "action_tags": list(ACTION_TAGS),
        }

    def reports(self, token, since_ts=None):
        """The caller's effective reports, newest first, for the history list."""
        agent_id, error = self._resolve(token)
        if error:
            return error
        rows = store.load_reports(agent_id, root=self.root, since_ts=since_ts)
        rows.sort(key=lambda item: float(item.get("ts", 0)), reverse=True)
        return {"ok": True, "status": 200, "agent_id": agent_id, "reports": rows}

    def amend(self, token, target, op, patch=None, amend_id=None):
        """Correct or delete one of the caller's own reports."""
        agent_id, error = self._resolve(token)
        if error:
            return error
        if op not in ("delete", "update"):
            return {"ok": False, "status": 400, "error": f"unknown op {op!r}"}

        # Resolve the target WITHIN this agent's own log. Looking it up
        # globally would let a token amend another user's reports.
        owned = {
            str(row.get("report_id"))
            for row in store.load_reports(agent_id, root=self.root)
        }
        if str(target) not in owned:
            return {"ok": False, "status": 404, "error": "unknown report"}

        store.append_amendment(
            agent_id,
            amend_id or f"amend-{target}-{len(owned)}",
            target,
            op,
            patch=patch,
            root=self.root,
        )
        return {"ok": True, "status": 200, "target": str(target), "op": op}

    def agents(self, token):
        """Agents this phone may twin.

        ``simulated`` marks the ones in ``CONFIG["agent_ids"]`` — a twin bound
        to an agent outside that set records reports normally but never
        mirrors, because nothing is stepping it. Surfacing the distinction
        beats letting someone pick a permanently motionless agent.
        """
        status = binding.token_status(token, path=self.bindings_path)
        if not status["valid"]:
            return _unauthorized()

        claimed = binding.claimed_agent_ids(
            path=self.bindings_path, exclude_token=token
        )
        rows = []
        for agent in roster.load_roster(self.roster_path):
            agent_id = agent["id"]
            rows.append({
                "id": agent_id,
                "name": agent["name"],
                "age": agent.get("age", ""),
                "job": agent.get("job", ""),
                "simulated": agent_id in self.simulated_ids,
                "taken": agent_id in claimed,
            })
        return {
            "ok": True,
            "status": 200,
            "agents": rows,
            "current": status["agent_id"],
        }

    def bind(self, token, agent_id):
        """Point this phone at an agent."""
        status = binding.token_status(token, path=self.bindings_path)
        if not status["valid"]:
            return _unauthorized()
        try:
            agent_id = int(agent_id)
        except (TypeError, ValueError):
            return {"ok": False, "status": 400, "error": "agent_id must be an integer"}

        known = {agent["id"] for agent in roster.load_roster(self.roster_path)}
        if known and agent_id not in known:
            return {"ok": False, "status": 404, "error": "unknown agent"}

        claimed = binding.claimed_agent_ids(
            path=self.bindings_path, exclude_token=token
        )
        if agent_id in claimed:
            return {"ok": False, "status": 409, "error": "agent already twinned"}

        binding.bind_token(token, agent_id, path=self.bindings_path)
        return {
            "ok": True,
            "status": 200,
            "agent_id": agent_id,
            "simulated": agent_id in self.simulated_ids,
        }

    def life(self, token):
        """What the agent is living: diary, state, goals."""
        agent_id, error = self._resolve(token)
        if error:
            return error
        return {
            "ok": True,
            "status": 200,
            "agent_id": agent_id,
            "diary": life.latest_diary(agent_id, diary_dir=self.diary_dir),
            "state": life.latest_state(agent_id, state_dir=self.state_dir),
            "goals": life.active_goals(agent_id, memory_dir=self.memory_dir),
        }

    def places(self, token, query="", limit=40):
        """Map nodes for manual location picking when GPS is unavailable."""
        agent_id, error = self._resolve(token)
        if error:
            return error

        snapshot = store.read_snapshot(agent_id, root=self.root)
        origin = (snapshot or {}).get("grid") or {"x": 0.0, "y": 0.0}
        needle = str(query or "").strip().lower()

        rows = []
        for node_id, node in ((self.city_map or {}).get("nodes") or {}).items():
            name = str(node.get("name") or node_id)
            if needle and needle not in name.lower() and needle not in str(node_id).lower():
                continue
            try:
                dx = float(node["x_km"]) - float(origin.get("x", 0)) * geo.KM_PER_GRID_X
                dy = float(node["y_km"]) - float(origin.get("y", 0)) * geo.KM_PER_GRID_Y
                distance = math.sqrt(dx * dx + dy * dy)
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({
                "id": node_id,
                "name": name,
                "category": node.get("category", ""),
                "distance_km": round(distance, 2),
                "lat": node.get("lat"),
                "lng": node.get("lng"),
            })
        rows.sort(key=lambda item: item["distance_km"])
        return {"ok": True, "status": 200, "places": rows[: max(1, int(limit))]}

    def trail(self, token, since_ts=None):
        """Ordered trail points for the canvas replay."""
        agent_id, error = self._resolve(token)
        if error:
            return error
        reports = store.load_reports(agent_id, root=self.root, since_ts=since_ts)
        reports.sort(key=lambda item: float(item.get("ts", 0)))
        points = [
            {
                "report_id": item.get("report_id"),
                "ts": item.get("ts"),
                "grid": item.get("grid"),
                "node_id": item.get("node_id"),
                "out_of_map": item.get("out_of_map"),
                "place": item.get("place", ""),
                "loc": item.get("loc"),
                "action_tag": item.get("action_tag"),
            }
            for item in reports
        ]
        return {"ok": True, "status": 200, "agent_id": agent_id, "points": points}
