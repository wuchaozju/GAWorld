"""Twin operations: authenticate, submit, snapshot, profile, trail.

All authorization lives here so the HTTP layer stays a routing shell. Every
operation takes a bearer token and resolves the agent id from it; no operation
accepts an agent id from the caller.
"""

from __future__ import annotations

import time

import math

from gaworld.io.avatar import build_agent_avatar_svg
from gaworld.twin import binding, geo, life, store


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


def _has_location(report):
    loc = report.get("loc") or {}
    try:
        lat, lng = float(loc["lat"]), float(loc["lng"])
    except (KeyError, TypeError, ValueError):
        return False
    # Existing clients use (0, 0) for activity-only reports, not a GPS fix.
    return (math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180
            and (lat != 0 or lng != 0))


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
    ):
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

    def authenticate(self, code):
        """Exchange an invite code for a bearer token."""
        token = binding.redeem_code(code, path=self.bindings_path)
        if token is None:
            return {"ok": False, "status": 403, "error": "invalid or revoked code"}
        return {
            "ok": True,
            "token": token,
            "label": binding.label_for_token(token, path=self.bindings_path),
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
            "out_of_map": located["out_of_map"],
            "action_tag": tag if tag in ACTION_TAGS else "other",
            "note": str(raw.get("note") or ""),
        }

    def submit(self, token, reports):
        """Store a batch of reports against the token's bound agent."""
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()
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
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()
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
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()
        label = binding.label_for_token(token, path=self.bindings_path)
        agent = {"id": agent_id, "name": label or f"agent_{agent_id}"}
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
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()
        rows = store.load_reports(agent_id, root=self.root, since_ts=since_ts)
        rows.sort(key=lambda item: float(item.get("ts", 0)), reverse=True)
        return {"ok": True, "status": 200, "agent_id": agent_id, "reports": rows}

    def amend(self, token, target, op, patch=None, amend_id=None):
        """Correct or delete one of the caller's own reports."""
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()
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

    def life(self, token):
        """What the agent is living: diary, state, goals."""
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()
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
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()

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
        agent_id = self._agent_for(token)
        if agent_id is None:
            return _unauthorized()
        reports = store.load_reports(agent_id, root=self.root, since_ts=since_ts)
        reports.sort(key=lambda item: float(item.get("ts", 0)))
        points = [
            {
                "report_id": item.get("report_id"),
                "ts": item.get("ts"),
                "grid": item.get("grid"),
                "node_id": item.get("node_id"),
                "out_of_map": item.get("out_of_map"),
                "has_location": _has_location(item),
                "action_tag": item.get("action_tag"),
            }
            for item in reports
        ]
        return {"ok": True, "status": 200, "agent_id": agent_id, "points": points}
