# Mobile Digital Twin Design

**Date:** 2026-08-08

**Status:** Approved

**Scope:** A mobile PWA that connects to a remote GAWorld server, reports the user's real location and current activity, drives a bound agent as a digital twin, and renders that agent's avatar and movement.

## 1. Goal

Let a small number of known users open a phone browser and:

1. Report their real location (GPS) and current activity (preset tag plus optional note) to a remote GAWorld server.
2. Have that data drive one bound agent — the user's digital twin — along three paths: state mirroring, perception injection, and offline profile calibration.
3. See their agent's generated avatar, its current state animation, and an animated replay of the day's movement trail.

### 1.1 Positioning

Research and demonstration use, not a consumer product. Users are known in advance (the author, collaborators, reviewers). This is a deliberate scope decision with consequences throughout:

- No registration, no password reset, no multi-tenant isolation beyond per-token agent binding.
- Invite codes are provisioned server-side by hand.
- No personal-information compliance workflow (consent flows, data export, right to erasure). **If this system is ever opened to real users, that gap must be closed before launch** — location history is sensitive personal data under PRC PIPL.

### 1.2 Non-Goals

- Real-time simulation at 1x wall-clock speed (`simulate_realtime`). Rejected: the server would have to run 24 hours to simulate one day, LLM cost would accrue in real time, and comparative experiments would become impractical.
- Ground-truth evaluation of simulated versus real trajectories. Deferred; it is a separate project with its own metric design.
- Native app or WeChat Mini Program. A PWA needs no app-store review and shares the existing `site/` toolchain.
- WebSocket push. With a handful of users, polling is sufficient and avoids pushing the stdlib HTTP server past what it does well.

## 2. Existing-System Fit

The design reuses:

- `gaworld/world/city_map.py:_lnglat_to_grid()` — real WGS84 to grid projection already exists; the map is anchored on Hangzhou.
- `gaworld/io/avatar.py` — deterministic SVG avatar generation from agent attributes.
- `gaworld/memory/experience.py:append_agent_episode()` — episodic memory append.
- `gaworld/cognition/realism.py:build_context_key()` and `update_habits_from_episode()` — habit formation from episodes.
- `gaworld/sim/pipeline.py` — the configurable 12-stage agent-step pipeline, which accepts custom `"module:function"` stages from `CONFIG["pipeline"]["agent_step"]`.
- The file-queue cross-process pattern established by `output/life_events/events.json`.
- The separate-server-process pattern established by `external_environment_server.py` and `distributed_comm_server.py`.

Business logic lives under `gaworld/twin/`. The HTTP layer does routing and authentication only.

## 3. Security Constraints

Two facts drive the architecture and are recorded here because violating either is silently catastrophic.

**3.1 The existing dashboard must not be exposed.** `dashboard_server.py` accepts unauthenticated POSTs to `/api/config` (writes global config), `/api/run/start` and `/api/run/stop` (spawns and kills simulation subprocesses), `/api/settings`, and `/api/population`. Binding it to `0.0.0.0` would grant config-write and process-spawn capability to anyone who scans the port. It stays on `127.0.0.1:8766`, unchanged.

**3.2 HTTPS is mandatory, not optional.** The browser Geolocation API is unavailable on non-HTTPS non-localhost origins. Any plain-HTTP deployment fails to collect location at all.

## 4. Selected Architecture

### 4.1 Process Topology

```
Phone PWA ──HTTPS──▶ Cloudflare Tunnel ──▶ twin_server.py  (:8767)
                                               │ writes files only;
                                               │ never touches simulation memory
                                               ▼
                                     output/twin/<agent_id>/
                                       ├─ reports.jsonl   append-only, single source of truth
                                       └─ snapshot.json   latest report, read by the mirror channel

dashboard_server.py (:8766, 127.0.0.1)   unchanged, not exposed
simulation subprocess                     reads snapshot / reports, writes state and memory
```

The three processes communicate only through files. Consequences:

- `twin_server` needs no access to simulation process memory and no knowledge of simulation internals.
- The phone works whether or not a simulation is running — avatar and trail rendering do not depend on the simulator being up.
- Real-time latency is bounded by the file poll interval (seconds), which is well within what this use case needs.

Cloudflare Tunnel provides TLS with no public IP and no certificate operations, and its Access layer is available as a second authentication factor if wanted later.

### 4.2 Single Source, Three Consumers

`reports.jsonl` is the only source of truth. All three channels derive from it and are mutually independent.

| Channel | Reads | Writes | When |
|---|---|---|---|
| A — Mirror | `snapshot.json` | agent `locations.current` and current action | every simulation tick |
| B — Perception injection | reports after the last consumed offset | episodic memory via `append_agent_episode()` | every simulation tick |
| C — Profile calibration | full `reports.jsonl` | habits / profile patch | offline script, **applied only after human review** |

Channel C deliberately does not write the profile automatically. Letting collected data silently rewrite an experimental subject destroys reproducibility: a later run could not be attributed to a config change versus an unnoticed profile drift.

### 4.3 Report Schema

```json
{
  "report_id": "uuid",
  "ts": 1754640000,
  "tz_offset": 480,
  "loc":   { "lat": 30.27, "lng": 120.15, "acc_m": 12, "source": "gps" },
  "grid":  { "x": 1.83, "y": -0.42 },
  "node_id": "cafe_wulin_01",
  "out_of_map": false,
  "action_tag": "commute",
  "note": ""
}
```

- `report_id` is client-generated and is the idempotency key.
- `grid` and `node_id` are computed server-side from `loc`; clients do not supply them.
- `loc.source` is `"gps"` or `"manual"`.
- **`agent_id` is deliberately absent from the request body.** It is resolved from the token. If it were in the body, any holder of a valid token could edit another user's agent by changing one field.

`action_tag` comes from a fixed vocabulary aligned with the agent action vocabulary, so channel A can write it directly and channel C can aggregate it without normalization. The optional free-text `note` carries what a tag cannot (mood, companions, context) and feeds channel B.

### 4.4 Authentication

An invite code is exchanged once for a token. The token is an opaque HMAC-signed string; the server stores only its hash. Each token is bound to exactly one `agent_id`.

Bindings live in `data/twin_bindings.json`: invite-code hash to `{agent_id, label, created_at, revoked}`.

All `twin_server` endpoints pass through one shared verification entry point. There are no unauthenticated paths other than the invite-code exchange itself.

### 4.5 Endpoints

`twin_server` exposes only these, which is the point of running it as a separate process:

| Endpoint | Purpose |
|---|---|
| `POST /api/twin/auth` | exchange invite code for token |
| `POST /api/twin/report` | submit reports; the body is always a JSON array of the section 4.3 object, length 1 in the normal case and longer for offline catch-up |
| `GET /api/twin/snapshot` | current twin state and sync freshness |
| `GET /api/twin/profile` | agent avatar SVG and display attributes |
| `GET /api/twin/trail` | today's trail points for the canvas replay |

Plus static serving of `site/mobile/`.

## 5. Pipeline Integration

### 5.1 Two Stages, Two Insertion Points

The default order is `prepare → perceive → interrupts → plan → adjust_activity → move → select_action → reflect → update_state → broadcast → memorize → record`.

```
perceive → [twin_perceive] → interrupts → plan → … → select_action → [twin_mirror] → reflect
              channel B                                                   channel A
```

- **`twin_perceive`** runs after `perceive`, so new reports enter the perception context and `plan` can see them. The agent decides how to react; nothing is forced.
- **`twin_mirror`** runs after `select_action`. The agent plans and moves normally, and only then is its location and action overwritten with real data. Placing it before `move` would let `move` overwrite it back — an ordering trap worth stating explicitly. Because the overwrite lands before `reflect` and `memorize`, reflection and memory are written against the real values.

Integration is pure configuration:

```python
CONFIG["pipeline"]["agent_step"] = [
    "prepare", "perceive", "gaworld.twin.stages:twin_perceive", "interrupts",
    "plan", "adjust_activity", "move", "select_action",
    "gaworld.twin.stages:twin_mirror", "reflect", "update_state",
    "broadcast", "memorize", "record",
]
```

`pipeline.py` and `run_simulation` are not modified. Disabling the twin means deleting two entries from a list, which also makes twin-on versus twin-off a clean experimental control.

### 5.2 New Intervention

`set_agent_state` accepts float values only (`gaworld/kernel/interventions.py`), so it cannot write the string-valued location and action. Add `set_agent_twin_state`, registered alongside the standard interventions and audited through the same `controller.intervention` record table.

The audit trail is a requirement, not a bonus: without it, post-hoc analysis cannot distinguish a behavior the simulation generated from one injected from reality.

### 5.3 Channel C

`scripts/twin_calibrate.py` reads the full `reports.jsonl`, aggregates frequent locations, daily rhythm, and commute patterns, and reuses `build_context_key()` and `update_habits_from_episode()` to produce a habits patch plus a human-readable diff. It writes nothing until a reviewer approves the diff.

## 6. Mobile Client

`site/mobile/`, a PWA. Phaser is deliberately not used: the `site/simviz/` viewer is built for desktop interaction and its vendored engine is poor value over mobile data and battery.

| Region | Implementation | Source |
|---|---|---|
| Avatar card | `avatar.py` SVG plus CSS keyframes for state animation | `/api/twin/profile` |
| Report panel | large tag-button grid, optional note, submit | local |
| Trail view | one `<canvas>`: today's polyline plus a current-position marker | `/api/twin/trail` |

"Animation" is therefore two distinct things: **state animation** of the avatar (CSS, switching posture with `action_tag`) and **temporal animation** of the trail (canvas replay along the day's timeline). Neither needs a game engine.

## 7. Error Handling

Each failure mode below is one that will actually occur, with an explicit fallback:

- **Geolocation permission denied** — switch to manual point selection, `loc.source = "manual"`. The feature continues to work.
- **User outside map coverage** (the map is anchored on Hangzhou) — set `out_of_map: true`. Channel A skips the location overwrite; channels B and C proceed normally. The user is *not* clamped to the map edge to fake success, because a fabricated position would silently corrupt both the mirror and the calibration data.
- **Phone offline** — queue in IndexedDB and resubmit on recovery. `report_id` makes the server idempotent, so a duplicate submission appends only one line.
- **Stale snapshot** (no report within the freshness threshold, a config value under `CONFIG["twin"]["snapshot_ttl_minutes"]`, default 30) — channel A does not overwrite, the agent reverts to autonomous behavior, and the phone shows an explicit "not synced" state rather than presenting a stale position as current.

## 8. Module Boundaries

```
gaworld/twin/
  __init__.py
  store.py       reports.jsonl / snapshot.json read-write, idempotent dedup
  binding.py     invite code to agent_id, token issue and verify
  geo.py         GPS → grid → nearest node (wraps _lnglat_to_grid)
  stages.py      twin_perceive / twin_mirror
gaworld/apps/twin_server.py   HTTP routing and auth only
site/mobile/                  PWA
scripts/twin_calibrate.py     channel C offline script
```

`store.py`, `binding.py`, and `geo.py` depend on neither HTTP nor the simulator, so each is unit-testable in isolation. `twin_server.py` holds no business logic, which keeps the publicly exposed process as thin as possible.

## 9. Testing

Python (pytest):

- **Authorization** — a token bound to agent A attempting to write agent B returns 403. This is the most important test, because agent identity comes from the token rather than the request body.
- **Idempotency** — the same `report_id` submitted twice appends exactly one line.
- **Coordinate round-trip** — reuse the existing `_lnglat_to_grid` round-trip property; add boundary cases for out-of-map coordinates.
- **Stage ordering** — assert that after `twin_mirror` the agent's `locations.current` holds the real value, and that the stage runs after `move`. This catches a reordering that would otherwise fail silently.
- **Freshness** — a stale snapshot produces no overwrite.
- **Calibration** — `twin_calibrate.py` writes nothing without explicit approval.

Frontend (plain node, no framework, matching the existing `.test.js` convention):

- `node site/mobile/app.test.js` — headless render smoke test asserting the first render produces content.

## 10. Follow-On Work

Out of scope here, listed so the boundary is explicit:

1. **Automatic activity inference** — infer activity from GPS dwell time and POI category, with the user confirming or correcting a pre-filled guess. Roughly twice the work of the preset-tag approach and better done once real data exists to validate against.
2. **Ground-truth comparison** — real trajectory versus simulated trajectory, with error metrics. Highest academic value, and a separate design.
3. **Map coverage beyond Hangzhou** — currently a hard constraint from the map anchor.
4. **Compliance work** — required before any non-research user is onboarded (see 1.1).
