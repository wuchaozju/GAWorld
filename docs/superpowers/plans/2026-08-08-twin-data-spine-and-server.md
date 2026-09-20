# Twin Data Spine & Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the authenticated ingestion server and data layer for the mobile digital twin, so a phone can exchange an invite code for a token, submit location/activity reports, and read back its bound agent's snapshot, avatar, and daily trail.

**Architecture:** Business logic lives in `gaworld/twin/` as three independent, HTTP-free, simulator-free modules (`geo`, `store`, `binding`) composed by a `TwinBackend` class. `gaworld/apps/twin_server.py` is a thin stdlib HTTP layer that does routing and authentication only. Reports land in an append-only `reports.jsonl` per agent — the single source of truth that later plans consume. `dashboard_server.py` is not touched.

**Tech Stack:** Python 3 stdlib only (`http.server`, `hashlib`, `secrets`, `json`, `threading`), pytest + unittest for tests. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-08-08-mobile-digital-twin-design.md`

---

## Deviation From Spec (approved before starting)

Spec §4.4 says the token is "an opaque HMAC-signed string; the server stores only its hash." This plan implements a **random opaque token whose SHA-256 hash is stored server-side**, with no HMAC signing.

Rationale: HMAC signing exists to make a token verifiable *without* server-side state. Since we store the hash anyway, the signature adds a secret to manage and rotate for zero security benefit. The spec's actual requirements — opaque to the client, only a hash at rest — are both met.

If you disagree, stop and raise it before Task 3.

**Second, smaller deviation:** spec §8 lists four modules under `gaworld/twin/`. This plan adds a fifth, `backend.py`, holding the `TwinBackend` composition class. Spec §8 requires `twin_server.py` to contain no business logic; without a composition layer, the authorization and enrichment logic would have nowhere to live but the HTTP handler. `backend.py` is what keeps the publicly exposed file thin.

---

## File Structure

| File | Responsibility |
|---|---|
| `gaworld/twin/__init__.py` | Package marker; no logic |
| `gaworld/twin/geo.py` | WGS84 → grid/km → nearest map node, with an out-of-map verdict |
| `gaworld/twin/store.py` | `reports.jsonl` / `snapshot.json` read-write, idempotent dedup, freshness |
| `gaworld/twin/binding.py` | Invite code ↔ agent_id, token issue/verify/revoke |
| `gaworld/twin/backend.py` | `TwinBackend`, composing the three above into the five operations |
| `gaworld/apps/twin_server.py` | HTTP routing, auth enforcement, static serving, CLI |
| `gaworld/settings/runtime.py` | Add the `twin` config block (modify) |
| `tests/test_twin_geo.py` | Projection and snapping |
| `tests/test_twin_store.py` | Append idempotency, snapshot, freshness |
| `tests/test_twin_binding.py` | Code redemption, token verify, revoke |
| `tests/test_twin_backend.py` | The five operations, including cross-agent authorization |

`geo`, `store`, and `binding` import neither HTTP nor the simulator, so each is unit-testable standing alone. `twin_server.py` holds no business logic — that is what keeps the publicly exposed process thin.

---

## Task 1: Geo projection and node snapping

**Files:**
- Create: `gaworld/twin/__init__.py`
- Create: `gaworld/twin/geo.py`
- Test: `tests/test_twin_geo.py`

- [ ] **Step 1: Create the package marker**

Create `gaworld/twin/__init__.py` with exactly this content:

```python
"""Mobile digital-twin subsystem: ingestion, storage, and agent binding."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_twin_geo.py`:

```python
import unittest

from gaworld.twin import geo
from gaworld.world.city_map import BASE_LAT, BASE_LNG, LAT_PER_KM, LNG_PER_KM


def _fake_map():
    """Two nodes 5 km apart on the x axis, built the way city_map builds them."""
    return {
        "nodes": {
            "home": {"id": "home", "name": "home", "x_km": 0.0, "y_km": 0.0},
            "office": {"id": "office", "name": "office", "x_km": 5.0, "y_km": 0.0},
        }
    }


def _lnglat_at_km(x_km, y_km):
    """Inverse of the projection, so tests can name a point in kilometres."""
    return (BASE_LNG + x_km * LNG_PER_KM, BASE_LAT + y_km * LAT_PER_KM)


class TestTwinGeo(unittest.TestCase):
    def test_project_round_trips_kilometres(self):
        lng, lat = _lnglat_at_km(3.0, -2.0)
        projected = geo.project(lng, lat)
        self.assertAlmostEqual(projected["x_km"], 3.0, places=2)
        self.assertAlmostEqual(projected["y_km"], -2.0, places=2)

    def test_locate_snaps_to_the_closest_node(self):
        lng, lat = _lnglat_at_km(4.6, 0.0)
        result = geo.locate(lng, lat, city_map=_fake_map(), max_snap_km=3.0)
        self.assertEqual(result["node_id"], "office")
        self.assertFalse(result["out_of_map"])
        self.assertAlmostEqual(result["snap_km"], 0.4, places=1)

    def test_locate_reports_out_of_map_instead_of_clamping(self):
        # 40 km away: far outside Hangzhou coverage. The nearest node must NOT
        # be returned, because a fabricated position would corrupt the mirror
        # channel and the calibration data downstream.
        lng, lat = _lnglat_at_km(40.0, 0.0)
        result = geo.locate(lng, lat, city_map=_fake_map(), max_snap_km=3.0)
        self.assertTrue(result["out_of_map"])
        self.assertIsNone(result["node_id"])

    def test_locate_handles_an_empty_map(self):
        result = geo.locate(120.15, 30.27, city_map={"nodes": {}}, max_snap_km=3.0)
        self.assertTrue(result["out_of_map"])
        self.assertIsNone(result["node_id"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_twin_geo.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'gaworld.twin.geo'`

- [ ] **Step 4: Write the implementation**

Create `gaworld/twin/geo.py`:

```python
"""Map real GPS fixes onto GAWorld city-map nodes.

A thin wrapper over the canonical projection in :mod:`gaworld.world.city_map`,
so the twin subsystem never re-derives the lat/lng maths and cannot drift from
it. Coordinates farther than ``max_snap_km`` from every node are reported as
out of map rather than snapped to the nearest edge node: the map is anchored on
Hangzhou, and a fabricated position would silently corrupt both the mirror
channel and the offline calibration data.
"""

from __future__ import annotations

import math

from gaworld.world.city_map import KM_PER_GRID_X, KM_PER_GRID_Y, _lnglat_to_grid


DEFAULT_MAX_SNAP_KM = 3.0


def project(lng, lat):
    """Project WGS84 to the city map's grid and kilometre offsets."""
    grid_x, grid_y = _lnglat_to_grid(lng, lat)
    return {
        "grid_x": round(grid_x, 4),
        "grid_y": round(grid_y, 4),
        "x_km": round(grid_x * KM_PER_GRID_X, 4),
        "y_km": round(grid_y * KM_PER_GRID_Y, 4),
    }


def nearest_node(city_map, x_km, y_km):
    """Return ``(node_id, distance_km)``, or ``(None, inf)`` for an empty map."""
    nodes = (city_map or {}).get("nodes") or {}
    best_id = None
    best_dist = math.inf
    for node_id, node in nodes.items():
        try:
            dx = float(node["x_km"]) - float(x_km)
            dy = float(node["y_km"]) - float(y_km)
        except (KeyError, TypeError, ValueError):
            # A node without usable coordinates is skipped rather than fatal:
            # one malformed entry should not break every incoming report.
            continue
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < best_dist:
            best_id = node_id
            best_dist = dist
    return best_id, best_dist


def locate(lng, lat, city_map=None, max_snap_km=DEFAULT_MAX_SNAP_KM):
    """Project a GPS fix and snap it to a node when one is close enough."""
    projected = project(lng, lat)
    node_id, dist_km = nearest_node(city_map, projected["x_km"], projected["y_km"])
    out_of_map = node_id is None or dist_km > float(max_snap_km)
    return {
        "grid": {"x": projected["grid_x"], "y": projected["grid_y"]},
        "node_id": None if out_of_map else node_id,
        "snap_km": None if node_id is None else round(dist_km, 3),
        "out_of_map": bool(out_of_map),
    }
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_twin_geo.py -v`

Expected: PASS, 4 tests

- [ ] **Step 6: Commit**

```bash
git add gaworld/twin/__init__.py gaworld/twin/geo.py tests/test_twin_geo.py
git commit -m "feat(twin): GPS to city-map node projection with out-of-map verdict"
```

---

## Task 2: Report store with idempotent append

**Files:**
- Create: `gaworld/twin/store.py`
- Test: `tests/test_twin_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_twin_store.py`:

```python
import os
import tempfile
import unittest

from gaworld.twin import store


def _report(report_id, ts, action_tag="commute"):
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": 30.27, "lng": 120.15, "acc_m": 12, "source": "gps"},
        "grid": {"x": 0.0, "y": 0.0},
        "node_id": "home",
        "out_of_map": False,
        "action_tag": action_tag,
        "note": "",
    }


class TestTwinStore(unittest.TestCase):
    def test_append_then_load_returns_the_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["duplicates"], 0)
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["report_id"], "a")

    def test_duplicate_report_id_appends_only_once(self):
        # The phone resubmits its offline queue after a flaky upload; the same
        # report_id must not produce a second line.
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            result = store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            self.assertEqual(result["accepted"], 0)
            self.assertEqual(result["duplicates"], 1)
            self.assertEqual(len(store.load_reports(7, root=tmpdir)), 1)

    def test_batch_dedupes_within_itself(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            batch = [_report("a", 1000), _report("a", 1000), _report("b", 1001)]
            result = store.append_reports(7, batch, root=tmpdir)
            self.assertEqual(result["accepted"], 2)
            self.assertEqual(result["duplicates"], 1)

    def test_snapshot_holds_the_latest_report_by_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Deliberately out of order: an offline flush can arrive late.
            store.append_reports(7, [_report("b", 2000, "work")], root=tmpdir)
            store.append_reports(7, [_report("a", 1000, "sleep")], root=tmpdir)
            snapshot = store.read_snapshot(7, root=tmpdir)
            self.assertEqual(snapshot["action_tag"], "work")
            self.assertEqual(snapshot["ts"], 2000)

    def test_agents_are_isolated_from_each_other(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            self.assertEqual(len(store.load_reports(8, root=tmpdir)), 0)
            self.assertIsNone(store.read_snapshot(8, root=tmpdir))

    def test_load_reports_can_filter_by_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(
                7, [_report("a", 1000), _report("b", 2000)], root=tmpdir
            )
            recent = store.load_reports(7, root=tmpdir, since_ts=1500)
            self.assertEqual([r["report_id"] for r in recent], ["b"])

    def test_is_fresh_uses_the_ttl(self):
        snapshot = _report("a", 1000)
        self.assertTrue(store.is_fresh(snapshot, now_ts=1000 + 29 * 60, ttl_minutes=30))
        self.assertFalse(store.is_fresh(snapshot, now_ts=1000 + 31 * 60, ttl_minutes=30))
        self.assertFalse(store.is_fresh(None, now_ts=1000, ttl_minutes=30))

    def test_corrupt_line_does_not_break_loading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            path = os.path.join(store.agent_dir(7, root=tmpdir), "reports.jsonl")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("{not json\n")
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(len(loaded), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_twin_store.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'gaworld.twin.store'`

- [ ] **Step 3: Write the implementation**

Create `gaworld/twin/store.py`:

```python
"""Append-only report storage for the mobile digital twin.

``reports.jsonl`` is the single source of truth. Every downstream consumer —
the mirror stage, the perception-injection stage, and the offline calibration
script — derives from it and none of them write to it.

``snapshot.json`` is a derived cache of the newest report by timestamp, kept so
the mirror stage and the phone can read current state without scanning the full
log. It is regenerated on every append, never edited independently.
"""

from __future__ import annotations

import json
import os
import threading


DEFAULT_ROOT = "output/twin"

# One lock for the whole subsystem. The server is threaded, and at this scale
# (a handful of users) per-agent locks would add contention bookkeeping for no
# measurable gain.
_LOCK = threading.RLock()


def agent_dir(agent_id, root=DEFAULT_ROOT):
    return os.path.join(str(root), f"agent_{int(agent_id)}")


def _reports_path(agent_id, root=DEFAULT_ROOT):
    return os.path.join(agent_dir(agent_id, root=root), "reports.jsonl")


def _snapshot_path(agent_id, root=DEFAULT_ROOT):
    return os.path.join(agent_dir(agent_id, root=root), "snapshot.json")


def load_reports(agent_id, root=DEFAULT_ROOT, since_ts=None):
    """Return stored reports in file order, optionally newer than ``since_ts``."""
    path = _reports_path(agent_id, root=root)
    if not os.path.exists(path):
        return []
    reports = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A truncated write (killed process, full disk) must not make
                # every later read fail. Skip the line and keep going.
                continue
            if since_ts is not None and float(record.get("ts", 0)) <= float(since_ts):
                continue
            reports.append(record)
    return reports


def append_reports(agent_id, reports, root=DEFAULT_ROOT):
    """Append reports, skipping any ``report_id`` already stored.

    Returns ``{"accepted": int, "duplicates": int}``.
    """
    with _LOCK:
        existing = {
            str(item.get("report_id"))
            for item in load_reports(agent_id, root=root)
            if item.get("report_id")
        }
        directory = agent_dir(agent_id, root=root)
        os.makedirs(directory, exist_ok=True)

        accepted = []
        duplicates = 0
        for record in reports or []:
            report_id = str(record.get("report_id") or "")
            if not report_id or report_id in existing:
                duplicates += 1
                continue
            existing.add(report_id)
            accepted.append(record)

        if accepted:
            with open(_reports_path(agent_id, root=root), "a", encoding="utf-8") as handle:
                for record in accepted:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            _refresh_snapshot(agent_id, root=root)

        return {"accepted": len(accepted), "duplicates": duplicates}


def _refresh_snapshot(agent_id, root=DEFAULT_ROOT):
    """Rewrite snapshot.json as the newest stored report by timestamp."""
    reports = load_reports(agent_id, root=root)
    if not reports:
        return
    newest = max(reports, key=lambda item: float(item.get("ts", 0)))
    directory = agent_dir(agent_id, root=root)
    os.makedirs(directory, exist_ok=True)
    with open(_snapshot_path(agent_id, root=root), "w", encoding="utf-8") as handle:
        json.dump(newest, handle, ensure_ascii=False, indent=2)


def read_snapshot(agent_id, root=DEFAULT_ROOT):
    """Return the newest report, or ``None`` when the agent has never reported."""
    path = _snapshot_path(agent_id, root=root)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def is_fresh(snapshot, now_ts, ttl_minutes):
    """Whether a snapshot is recent enough for the mirror channel to apply."""
    if not snapshot:
        return False
    try:
        age_seconds = float(now_ts) - float(snapshot.get("ts", 0))
    except (TypeError, ValueError):
        return False
    return 0 <= age_seconds <= float(ttl_minutes) * 60
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_twin_store.py -v`

Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add gaworld/twin/store.py tests/test_twin_store.py
git commit -m "feat(twin): append-only report store with idempotent dedup"
```

---

## Task 3: Invite codes and tokens

**Files:**
- Create: `gaworld/twin/binding.py`
- Test: `tests/test_twin_binding.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_twin_binding.py`:

```python
import os
import tempfile
import unittest

from gaworld.twin import binding


class TestTwinBinding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "twin_bindings.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_issue_code_then_redeem_returns_a_token(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        self.assertTrue(token)
        self.assertEqual(binding.resolve_token(token, path=self.path), 7)

    def test_the_plaintext_code_is_never_persisted(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        with open(self.path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn(code, raw)

    def test_the_plaintext_token_is_never_persisted(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        with open(self.path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn(token, raw)

    def test_unknown_code_is_rejected(self):
        self.assertIsNone(binding.redeem_code("nope", path=self.path))

    def test_unknown_token_resolves_to_none(self):
        self.assertIsNone(binding.resolve_token("nope", path=self.path))

    def test_a_code_can_be_redeemed_more_than_once(self):
        # The user may reinstall the PWA or clear site data. Each redemption
        # issues a fresh token; both remain valid until revoked.
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        first = binding.redeem_code(code, path=self.path)
        second = binding.redeem_code(code, path=self.path)
        self.assertNotEqual(first, second)
        self.assertEqual(binding.resolve_token(first, path=self.path), 7)
        self.assertEqual(binding.resolve_token(second, path=self.path), 7)

    def test_revoked_code_stops_issuing_tokens(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        binding.revoke_code(code, path=self.path)
        self.assertIsNone(binding.redeem_code(code, path=self.path))

    def test_revoking_a_code_invalidates_tokens_already_issued_from_it(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        binding.revoke_code(code, path=self.path)
        self.assertIsNone(binding.resolve_token(token, path=self.path))

    def test_two_agents_get_distinct_bindings(self):
        code_a = binding.issue_code(agent_id=7, label="a", path=self.path)
        code_b = binding.issue_code(agent_id=8, label="b", path=self.path)
        token_a = binding.redeem_code(code_a, path=self.path)
        token_b = binding.redeem_code(code_b, path=self.path)
        self.assertEqual(binding.resolve_token(token_a, path=self.path), 7)
        self.assertEqual(binding.resolve_token(token_b, path=self.path), 8)

    def test_label_for_token(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        self.assertEqual(binding.label_for_token(token, path=self.path), "cw")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_twin_binding.py -v`

Expected: FAIL — `ImportError: cannot import name 'binding' from 'gaworld.twin'`

(The package `gaworld/twin/__init__.py` already exists from Task 1, so a `from package import submodule` of a missing submodule raises `ImportError`, not `ModuleNotFoundError`.)

- [ ] **Step 3: Write the implementation**

Create `gaworld/twin/binding.py`:

```python
"""Invite codes and bearer tokens binding a phone to exactly one agent.

Both invite codes and tokens are random opaque strings; only their SHA-256
hashes are stored. Reading the bindings file therefore does not let anyone
authenticate as a user.

The agent id is resolved from the token and never read from a request body.
That is the whole point of this module: if agent identity travelled in the
payload, any holder of a valid token could edit another user's agent by
changing one field.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading


DEFAULT_PATH = "data/twin_bindings.json"

_LOCK = threading.RLock()


def _hash(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _load(path):
    if not os.path.exists(path):
        return {"codes": [], "tokens": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"codes": [], "tokens": []}
    data.setdefault("codes", [])
    data.setdefault("tokens", [])
    return data


def _save(data, path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _find_code(data, code_hash):
    for record in data["codes"]:
        if record.get("code_hash") == code_hash:
            return record
    return None


def issue_code(agent_id, label="", path=DEFAULT_PATH):
    """Create an invite code bound to ``agent_id``. Returns the plaintext code."""
    code = secrets.token_urlsafe(9)
    with _LOCK:
        data = _load(path)
        data["codes"].append(
            {
                "code_hash": _hash(code),
                "agent_id": int(agent_id),
                "label": str(label),
                "revoked": False,
            }
        )
        _save(data, path)
    return code


def redeem_code(code, path=DEFAULT_PATH):
    """Exchange an invite code for a token, or ``None`` if unknown or revoked."""
    with _LOCK:
        data = _load(path)
        record = _find_code(data, _hash(code))
        if record is None or record.get("revoked"):
            return None
        token = secrets.token_urlsafe(32)
        data["tokens"].append(
            {
                "token_hash": _hash(token),
                "code_hash": record["code_hash"],
                "agent_id": int(record["agent_id"]),
            }
        )
        _save(data, path)
        return token


def _token_record(data, token):
    token_hash = _hash(token)
    for record in data["tokens"]:
        if record.get("token_hash") == token_hash:
            return record
    return None


def resolve_token(token, path=DEFAULT_PATH):
    """Return the bound ``agent_id``, or ``None`` when invalid or revoked."""
    if not token:
        return None
    with _LOCK:
        data = _load(path)
        record = _token_record(data, token)
        if record is None:
            return None
        code = _find_code(data, record.get("code_hash"))
        # Revoking the code must kill every token minted from it, otherwise
        # revocation would not actually cut off access.
        if code is None or code.get("revoked"):
            return None
        return int(record["agent_id"])


def label_for_token(token, path=DEFAULT_PATH):
    """Return the display label bound to a token, or ``""``."""
    with _LOCK:
        data = _load(path)
        record = _token_record(data, token)
        if record is None:
            return ""
        code = _find_code(data, record.get("code_hash"))
        if code is None or code.get("revoked"):
            return ""
        return str(code.get("label", ""))


def revoke_code(code, path=DEFAULT_PATH):
    """Revoke an invite code and every token issued from it."""
    with _LOCK:
        data = _load(path)
        record = _find_code(data, _hash(code))
        if record is None:
            return False
        record["revoked"] = True
        _save(data, path)
        return True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_twin_binding.py -v`

Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add gaworld/twin/binding.py tests/test_twin_binding.py
git commit -m "feat(twin): invite-code and token binding with hash-only storage"
```

---

## Task 4: Config block

**Files:**
- Modify: `gaworld/settings/runtime.py`

- [ ] **Step 1: Add the config block**

Open `gaworld/settings/runtime.py` and find the `"real_map_path": "data/hangzhou_real.geojson",` line (around line 89). Insert the following block immediately after it, matching the surrounding indentation:

```python
        # Mobile digital twin. The twin server is a SEPARATE process from the
        # dashboard (see gaworld/apps/twin_server.py) because the dashboard
        # accepts unauthenticated config-write and process-spawn POSTs and
        # must never be exposed publicly.
        "twin": {
            "enabled": False,
            "root": "output/twin",
            "bindings_path": "data/twin_bindings.json",
            # How stale a snapshot may be before the mirror channel stops
            # applying it and the phone shows "not synced".
            "snapshot_ttl_minutes": 30,
            # A GPS fix farther than this from every map node is reported as
            # out of map rather than snapped to the nearest edge node.
            "max_snap_km": 3.0,
        },
```

- [ ] **Step 2: Verify the config loads**

Run:

```bash
python3 -c "from gaworld.settings import CONFIG; print(CONFIG['twin'])"
```

Expected output:

```
{'enabled': False, 'root': 'output/twin', 'bindings_path': 'data/twin_bindings.json', 'snapshot_ttl_minutes': 30, 'max_snap_km': 3.0}
```

- [ ] **Step 3: Verify nothing else broke**

Run: `python3 -m pytest tests/ -q -x`

Expected: the suite passes at the same rate as before your change. If a test fails, confirm it also fails on `git stash` before blaming this task.

- [ ] **Step 4: Commit**

```bash
git add gaworld/settings/runtime.py
git commit -m "feat(twin): add twin config block"
```

---

## Task 5: TwinBackend

**Files:**
- Create: `gaworld/twin/backend.py`
- Test: `tests/test_twin_backend.py`

`TwinBackend` composes `geo`, `store`, and `binding` into the five operations the HTTP layer exposes. It holds all authorization logic, so `twin_server.py` can stay a routing shell.

- [ ] **Step 1: Write the failing test**

Create `tests/test_twin_backend.py`:

```python
import os
import tempfile
import unittest

from gaworld.twin import binding
from gaworld.twin.backend import TwinBackend
from gaworld.world.city_map import BASE_LAT, BASE_LNG, LAT_PER_KM, LNG_PER_KM


def _fake_map():
    return {
        "nodes": {
            "home": {"id": "home", "name": "home", "x_km": 0.0, "y_km": 0.0},
            "office": {"id": "office", "name": "office", "x_km": 5.0, "y_km": 0.0},
        }
    }


def _lnglat_at_km(x_km, y_km):
    return (BASE_LNG + x_km * LNG_PER_KM, BASE_LAT + y_km * LAT_PER_KM)


def _raw(report_id, x_km=0.0, ts=1000, action_tag="commute", note=""):
    lng, lat = _lnglat_at_km(x_km, 0.0)
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": lat, "lng": lng, "acc_m": 10, "source": "gps"},
        "action_tag": action_tag,
        "note": note,
    }


class TestTwinBackend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "twin")
        self.bindings = os.path.join(self._tmp.name, "twin_bindings.json")
        self.backend = TwinBackend(
            root=self.root,
            bindings_path=self.bindings,
            city_map=_fake_map(),
            snapshot_ttl_minutes=30,
            max_snap_km=3.0,
        )
        self.code = binding.issue_code(agent_id=7, label="cw", path=self.bindings)
        self.token = binding.redeem_code(self.code, path=self.bindings)

    def tearDown(self):
        self._tmp.cleanup()

    def test_authenticate_exchanges_a_code_for_a_token(self):
        result = self.backend.authenticate(self.code)
        self.assertTrue(result["ok"])
        self.assertTrue(result["token"])
        self.assertEqual(result["label"], "cw")

    def test_authenticate_rejects_a_bad_code(self):
        result = self.backend.authenticate("nope")
        self.assertFalse(result["ok"])

    def test_submit_enriches_the_report_with_geo_fields(self):
        result = self.backend.submit(self.token, [_raw("a", x_km=4.8)])
        self.assertTrue(result["ok"])
        self.assertEqual(result["accepted"], 1)
        stored = self.backend.snapshot(self.token)["report"]
        self.assertEqual(stored["node_id"], "office")
        self.assertFalse(stored["out_of_map"])
        self.assertIn("grid", stored)

    def test_submit_rejects_an_invalid_token(self):
        result = self.backend.submit("nope", [_raw("a")])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 401)

    def test_a_client_cannot_write_another_agents_data(self):
        # The single most important test in this plan. agent_id must come from
        # the token, so a body claiming a different agent changes nothing.
        other_code = binding.issue_code(agent_id=8, label="other", path=self.bindings)
        other_token = binding.redeem_code(other_code, path=self.bindings)
        forged = _raw("a")
        forged["agent_id"] = 7
        self.backend.submit(other_token, [forged])

        # Agent 7 (this test's token) must still have nothing stored.
        self.assertIsNone(self.backend.snapshot(self.token)["report"])
        # And the write must have landed on agent 8 instead.
        self.assertIsNotNone(self.backend.snapshot(other_token)["report"])

    def test_out_of_map_report_is_stored_and_flagged(self):
        result = self.backend.submit(self.token, [_raw("a", x_km=40.0)])
        self.assertTrue(result["ok"])
        stored = self.backend.snapshot(self.token)["report"]
        self.assertTrue(stored["out_of_map"])
        self.assertIsNone(stored["node_id"])

    def test_snapshot_reports_freshness(self):
        self.backend.submit(self.token, [_raw("a", ts=1000)])
        fresh = self.backend.snapshot(self.token, now_ts=1000 + 60)
        self.assertTrue(fresh["fresh"])
        stale = self.backend.snapshot(self.token, now_ts=1000 + 60 * 60)
        self.assertFalse(stale["fresh"])

    def test_profile_returns_an_svg_avatar(self):
        profile = self.backend.profile(self.token)
        self.assertTrue(profile["ok"])
        self.assertEqual(profile["agent_id"], 7)
        self.assertIn("<svg", profile["avatar_svg"])

    def test_trail_returns_points_within_the_window(self):
        self.backend.submit(
            self.token,
            [_raw("a", x_km=0.0, ts=1000), _raw("b", x_km=5.0, ts=2000)],
        )
        trail = self.backend.trail(self.token, since_ts=1500)
        self.assertEqual(len(trail["points"]), 1)
        self.assertEqual(trail["points"][0]["report_id"], "b")

    def test_trail_points_carry_coordinates_and_tag(self):
        self.backend.submit(self.token, [_raw("a", x_km=5.0, action_tag="work")])
        point = self.backend.trail(self.token)["points"][0]
        self.assertIn("grid", point)
        self.assertEqual(point["action_tag"], "work")
        self.assertEqual(point["node_id"], "office")

    def test_every_read_operation_rejects_an_invalid_token(self):
        for call in (self.backend.snapshot, self.backend.profile, self.backend.trail):
            with self.subTest(call=call.__name__):
                result = call("nope")
                self.assertFalse(result["ok"])
                self.assertEqual(result["status"], 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_twin_backend.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'gaworld.twin.backend'`

(This one really is `ModuleNotFoundError`: the test imports `from gaworld.twin.backend import TwinBackend`, a direct submodule import, rather than `from gaworld.twin import backend`.)

- [ ] **Step 3: Write the implementation**

Create `gaworld/twin/backend.py`:

```python
"""Twin operations: authenticate, submit, snapshot, profile, trail.

All authorization lives here so the HTTP layer stays a routing shell. Every
operation takes a bearer token and resolves the agent id from it; no operation
accepts an agent id from the caller.
"""

from __future__ import annotations

import time

from gaworld.io.avatar import build_agent_avatar_svg
from gaworld.twin import binding, geo, store


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
    ):
        self.root = root
        self.bindings_path = bindings_path
        self.city_map = city_map or {"nodes": {}}
        self.snapshot_ttl_minutes = float(snapshot_ttl_minutes)
        self.max_snap_km = float(max_snap_km)

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
                "action_tag": item.get("action_tag"),
            }
            for item in reports
        ]
        return {"ok": True, "status": 200, "agent_id": agent_id, "points": points}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_twin_backend.py -v`

Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add gaworld/twin/backend.py tests/test_twin_backend.py
git commit -m "feat(twin): TwinBackend with token-derived agent authorization"
```

---

## Task 6: HTTP server

**Files:**
- Create: `gaworld/apps/twin_server.py`
- Test: `tests/test_twin_server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_twin_server.py`:

```python
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from gaworld.apps import twin_server
from gaworld.twin import binding
from gaworld.twin.backend import TwinBackend


def _fake_map():
    return {"nodes": {"home": {"id": "home", "name": "home", "x_km": 0.0, "y_km": 0.0}}}


def _request(url, payload=None, token=None):
    """Return (status, parsed_body)."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestTwinServer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bindings = os.path.join(self._tmp.name, "twin_bindings.json")
        backend = TwinBackend(
            root=os.path.join(self._tmp.name, "twin"),
            bindings_path=self.bindings,
            city_map=_fake_map(),
        )
        handler = twin_server.make_handler(backend)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self.code = binding.issue_code(agent_id=7, label="cw", path=self.bindings)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def _token(self):
        _, body = _request(f"{self.base}/api/twin/auth", {"code": self.code})
        return body["token"]

    def test_auth_returns_a_token(self):
        status, body = _request(f"{self.base}/api/twin/auth", {"code": self.code})
        self.assertEqual(status, 200)
        self.assertTrue(body["token"])

    def test_auth_rejects_a_bad_code(self):
        status, _ = _request(f"{self.base}/api/twin/auth", {"code": "nope"})
        self.assertEqual(status, 403)

    def test_report_requires_a_token(self):
        status, _ = _request(f"{self.base}/api/twin/report", [])
        self.assertEqual(status, 401)

    def test_report_round_trip(self):
        token = self._token()
        payload = [
            {
                "report_id": "a",
                "ts": 1000,
                "loc": {"lat": 30.2741, "lng": 120.1551, "source": "gps"},
                "action_tag": "work",
            }
        ]
        status, body = _request(f"{self.base}/api/twin/report", payload, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)

        status, body = _request(f"{self.base}/api/twin/snapshot", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["report"]["action_tag"], "work")

    def test_report_rejects_a_non_array_body(self):
        token = self._token()
        status, _ = _request(f"{self.base}/api/twin/report", {"report_id": "a"}, token=token)
        self.assertEqual(status, 400)

    def test_profile_and_trail_require_a_token(self):
        for path in ("/api/twin/profile", "/api/twin/trail", "/api/twin/snapshot"):
            with self.subTest(path=path):
                status, _ = _request(f"{self.base}{path}")
                self.assertEqual(status, 401)

    def test_profile_returns_an_avatar(self):
        status, body = _request(f"{self.base}/api/twin/profile", token=self._token())
        self.assertEqual(status, 200)
        self.assertIn("<svg", body["avatar_svg"])

    def test_dashboard_endpoints_are_not_reachable(self):
        # The whole reason this is a separate process: none of the dashboard's
        # unauthenticated config-write or process-spawn routes may exist here.
        for path in ("/api/config", "/api/run/start", "/api/settings", "/api/population"):
            with self.subTest(path=path):
                status, _ = _request(f"{self.base}{path}", {}, token=self._token())
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_twin_server.py -v`

Expected: FAIL — `ImportError: cannot import name 'twin_server' from 'gaworld.apps'`

- [ ] **Step 3: Write the implementation**

Create `gaworld/apps/twin_server.py`:

```python
"""Public-facing HTTP server for the mobile digital twin.

Deliberately a SEPARATE process from ``dashboard_server``. The dashboard
accepts unauthenticated POSTs to ``/api/config`` (writes global config) and
``/api/run/start`` (spawns simulation subprocesses); exposing that process
publicly would hand config-write and process-spawn capability to anyone who
scans the port. This server exposes five authenticated endpoints and the
mobile static bundle, and nothing else.

Routing and authentication only — all behaviour lives in
:class:`gaworld.twin.backend.TwinBackend`.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld.settings import CONFIG
from gaworld.twin.backend import TwinBackend


REPO_ROOT = str(Path(__file__).resolve().parents[2])
MAX_BODY_BYTES = 1_000_000


def make_handler(backend):
    """Build a request handler class bound to ``backend``."""

    class TwinHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=REPO_ROOT, **kwargs)

        # -- helpers ----------------------------------------------------

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _reply(self, result):
            """Send a backend result, using its own status field."""
            status = int(result.get("status", 200 if result.get("ok") else 400))
            self._json(result, status=status)

        def _token(self):
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                return header[len("Bearer "):].strip()
            return ""

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return None
            if length > MAX_BODY_BYTES:
                raise ValueError("request body too large")
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def log_message(self, fmt, *args):
            # Default logging writes the full request line to stderr. This
            # server is internet-facing, so keep tokens out of the logs.
            return

        # -- routing ----------------------------------------------------

        def do_GET(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)

            if path == "/api/twin/snapshot":
                return self._reply(backend.snapshot(self._token()))
            if path == "/api/twin/profile":
                return self._reply(backend.profile(self._token()))
            if path == "/api/twin/trail":
                since = query.get("since_ts", [None])[0]
                return self._reply(
                    backend.trail(self._token(), since_ts=float(since) if since else None)
                )
            if path.startswith("/api/"):
                return self._json({"error": "not found"}, status=404)

            if path in ("/", "/m", "/m/"):
                self.path = "/site/mobile/index.html"
            return super().do_GET()

        def do_POST(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            try:
                body = self._body()
            except (ValueError, json.JSONDecodeError) as exc:
                return self._json({"ok": False, "error": str(exc)}, status=400)

            if path == "/api/twin/auth":
                code = (body or {}).get("code", "") if isinstance(body, dict) else ""
                return self._reply(backend.authenticate(code))
            if path == "/api/twin/report":
                return self._reply(backend.submit(self._token(), body))
            return self._json({"error": "not found"}, status=404)

    return TwinHandler


def build_backend(config=None):
    """Build a backend from CONFIG, loading the city map for node snapping."""
    cfg = dict((config or CONFIG).get("twin") or {})
    city_map = None
    try:
        from gaworld.world.city_map import load_city_map_cached

        map_path = os.path.join(REPO_ROOT, (config or CONFIG).get("map_path", "data/citymap.md"))
        city_map = load_city_map_cached(map_path)
    except Exception:
        # Without a map every fix is reported out of map, which is the correct
        # conservative behaviour: better than snapping to a fabricated node.
        city_map = {"nodes": {}}
    return TwinBackend(
        root=cfg.get("root", "output/twin"),
        bindings_path=cfg.get("bindings_path", "data/twin_bindings.json"),
        city_map=city_map,
        snapshot_ttl_minutes=cfg.get("snapshot_ttl_minutes", 30),
        max_snap_km=cfg.get("max_snap_km", 3.0),
    )


def run_server(host="127.0.0.1", port=8767, backend=None):
    backend = backend or build_backend()
    server = ThreadingHTTPServer((host, int(port)), make_handler(backend))
    print(f"GAWorld twin server: http://{host}:{int(port)}/")
    print("Expose it over HTTPS (Cloudflare Tunnel); Geolocation needs TLS.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Serve the GAWorld mobile twin API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--issue-code", type=int, metavar="AGENT_ID",
                        help="print a new invite code for AGENT_ID and exit")
    parser.add_argument("--label", default="", help="display label for --issue-code")
    args = parser.parse_args()

    if args.issue_code is not None:
        from gaworld.twin import binding

        cfg = CONFIG.get("twin") or {}
        code = binding.issue_code(
            agent_id=args.issue_code,
            label=args.label,
            path=cfg.get("bindings_path", "data/twin_bindings.json"),
        )
        print(code)
    else:
        run_server(host=args.host, port=args.port)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_twin_server.py -v`

Expected: PASS, 8 tests

Note: `test_profile_and_trail_require_a_token` exercises GET without a token; `do_GET` reaches the backend, which returns 401 because no agent resolves. The static fallthrough is only reached for non-`/api/` paths.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`

Expected: no new failures versus `main`.

- [ ] **Step 6: Commit**

```bash
git add gaworld/apps/twin_server.py tests/test_twin_server.py
git commit -m "feat(twin): standalone twin HTTP server with five authenticated endpoints"
```

---

## Task 7: Manual end-to-end verification

**Files:** none (verification only)

This proves the deliverable: a real client can authenticate and round-trip a report.

- [ ] **Step 1: Issue an invite code**

Run:

```bash
python3 -m gaworld.apps.twin_server --issue-code 1 --label "test user"
```

Expected: a short URL-safe string on stdout (for example `xK3mQp7Rt9Zw`). Copy it.

- [ ] **Step 2: Start the server**

Run in a second terminal:

```bash
python3 -m gaworld.apps.twin_server --port 8767
```

Expected: `GAWorld twin server: http://127.0.0.1:8767/`

- [ ] **Step 3: Exchange the code for a token**

Replace `PASTE_CODE` with the code from Step 1:

```bash
curl -s -X POST http://127.0.0.1:8767/api/twin/auth -H 'Content-Type: application/json' -d '{"code":"PASTE_CODE"}'
```

Expected: JSON containing `"ok": true` and a `token` field. Copy the token.

- [ ] **Step 4: Submit a report**

Replace `PASTE_TOKEN`:

```bash
curl -s -X POST http://127.0.0.1:8767/api/twin/report -H 'Content-Type: application/json' -H 'Authorization: Bearer PASTE_TOKEN' -d '[{"report_id":"manual-1","ts":1754640000,"tz_offset":480,"loc":{"lat":30.2741,"lng":120.1551,"acc_m":10,"source":"gps"},"action_tag":"work","note":"手动验证"}]'
```

Expected: `{"ok": true, "status": 200, "accepted": 1, "duplicates": 0}`

- [ ] **Step 5: Confirm idempotency against a live server**

Run the exact same command from Step 4 again.

Expected: `"accepted": 0, "duplicates": 1`

- [ ] **Step 6: Read the snapshot back**

```bash
curl -s http://127.0.0.1:8767/api/twin/snapshot -H 'Authorization: Bearer PASTE_TOKEN'
```

Expected: JSON with `"agent_id": 1`, a `report` whose `action_tag` is `work`, a server-computed `node_id` and `grid`, and a `fresh` field.

- [ ] **Step 7: Confirm the dashboard surface is absent**

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8767/api/config -H 'Content-Type: application/json' -d '{}'
```

Expected: `404`. If this returns anything else, stop — the process isolation that justifies this architecture is broken.

- [ ] **Step 8: Stop the server and clean up**

Press Ctrl+C in the server terminal, then:

```bash
rm -rf output/twin/agent_1 && git checkout data/twin_bindings.json 2>/dev/null || rm -f data/twin_bindings.json
```

- [ ] **Step 9: Make sure reports and bindings stay out of git**

`output/twin/` holds real location history and `data/twin_bindings.json` holds live credential hashes. Neither belongs in the repository. Check both:

```bash
git check-ignore -q output/twin && echo "output ok" || echo 'output/twin/' >> .gitignore
git check-ignore -q data/twin_bindings.json && echo "bindings ok" || echo 'data/twin_bindings.json' >> .gitignore
```

Then commit only if `.gitignore` actually changed:

```bash
git diff --quiet .gitignore || (git add .gitignore && git commit -m "chore(twin): ignore twin reports and bindings")
```

---

## Done When

- `python3 -m pytest tests/test_twin_*.py -v` passes (41 tests across five files).
- `python3 -m pytest tests/ -q` shows no new failures versus `main`.
- Task 7's manual round-trip succeeds, including the 404 on `/api/config`.
- `data/twin_bindings.json` is not committed with real codes in it.

## Deliberately Not In This Plan

- `twin_perceive` / `twin_mirror` pipeline stages and the `set_agent_twin_state` intervention — Plan 2.
- `scripts/twin_calibrate.py` — Plan 2.
- `site/mobile/` PWA, including the IndexedDB offline queue — Plan 3. Task 6 already routes `/` and `/m` to `site/mobile/index.html`, so that path 404s until Plan 3 lands. That is expected.
- Cloudflare Tunnel setup — deployment, documented in the spec, not code.
