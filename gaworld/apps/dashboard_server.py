import atexit
import csv
import datetime
import math
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld.settings import CONFIG
from gaworld.apps import analytics, replay_runs
from gaworld.events import candidates as candidate_events
from gaworld.events.life import add_life_event, list_life_event_templates, list_life_events
from gaworld.family.lifecycle import family_facts
from gaworld.integrations.fos_prompt import generate_fos_prompt
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard")


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_ROOT = os.path.join(REPO_ROOT, "site", "dashboard")
DASHBOARD_CONFIG_PATH = os.path.join(REPO_ROOT, "dashboard_config.json")
PROFILE_PATH = os.path.join(REPO_ROOT, CONFIG.get("md_path", "data/hangzhou_profiles_with_names.md"))
STATE_CSV_PATH = os.path.join(REPO_ROOT, CONFIG.get("csv_path", "data/hangzhou_agents_state_init.csv"))
ECONOMY_SNAPSHOT_PATH = os.path.join(REPO_ROOT, "output", "economy", "wealth_snapshot.csv")
#: Kernel Recorder output (one JSONL per table). Panels that read a plugin's
#: recorded stream resolve it from here so tests can redirect it.
RECORDS_DIR = os.path.join(REPO_ROOT, "output", "records")
SKILLS_DIR = os.path.join(REPO_ROOT, CONFIG.get("skills", {}).get("global_dir", "data/skills"))
CAPABILITIES_CACHE_PATH = os.path.join(
    REPO_ROOT, CONFIG.get("real_work", {}).get("capabilities_cache", "output/work/capabilities.json")
)
RELAY_STATE_PATH = os.path.join(
    REPO_ROOT,
    CONFIG.get("distributed", {}).get("server", {}).get("state_path", "output/distributed/relay_state.json"),
)
RUN_LOG_PATH = os.path.join(REPO_ROOT, "output", "dashboard", "simulation_run.log")
TODO_BOARD_PATH = os.path.join(REPO_ROOT, "output", "dashboard", "todo_board.json")
#: Upper bound for the first (non-incremental) run-log read. Later polls only
#: ship the bytes appended since the client's offset, so this only caps how far
#: back a freshly opened page starts; the Markdown export is never truncated.
RUN_LOG_VIEW_MAX_BYTES = 8 * 1024 * 1024
PROFILE_HEADER_RE = re.compile(r"^## Profile\s+(\d+)\s*[｜|]\s*(.+?)\s*$", re.MULTILINE)

# The nine normalized [0,1] state variables that seed each agent. Order matters
# only for display; the CSV column order is preserved on write regardless.
STATE_VAR_KEYS = (
    "emotion",
    "stress",
    "econ_security",
    "city_identity",
    "policy_sensitivity",
    "platform_dependence",
    "risk_preference",
    "voice_propensity",
    "mobility_intent",
)

RUN_STATE = {
    "process": None,
    "started_at": None,
    "log_path": RUN_LOG_PATH,
    # Pending "定时运行": the timer thread that will start the run, the wall
    # clock it fires at, the payload to start with, and the error a fired
    # timer left behind (so a failed auto-start is visible in the panel).
    "schedule": None,
}

_SCHEDULE_LOCK = threading.Lock()
TODO_LOCK = threading.RLock()

_COLLABORATION_SERVICE = None
_COLLABORATION_LOCK = threading.Lock()


def _deep_update(base, patch):
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return base
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _read_json_file(path, default=None):
    if not os.path.exists(path):
        return {} if default is None else default
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default
    return payload


def _atomic_write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _todo_board_payload():
    with TODO_LOCK:
        payload = _read_json_file(TODO_BOARD_PATH, {"items": []})
        if isinstance(payload, list):
            payload = {"items": payload}
        if not isinstance(payload, dict):
            payload = {"items": []}
        items = payload.get("items", [])
        return {"items": items if isinstance(items, list) else []}


def _save_todo_board(items):
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    with TODO_LOCK:
        payload = {
            "items": items,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _atomic_write_json(TODO_BOARD_PATH, payload)
        return {"ok": True, **payload}


def _normalize_todo_item(payload, existing=None):
    if not isinstance(payload, dict):
        raise ValueError("todo payload must be an object")
    item = dict(existing or {})
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if not item.get("id"):
        item["id"] = str(uuid.uuid4())
        item["createdAt"] = now
    for key in ("title", "proposer", "details", "priority", "status", "owner"):
        if key in payload:
            item[key] = str(payload.get(key, "")).strip()
    item.setdefault("priority", "medium")
    item.setdefault("status", "pending")
    item.setdefault("owner", "")
    item.setdefault("createdAt", now)
    item["updatedAt"] = now
    if not item.get("title") or not item.get("proposer") or not item.get("details"):
        raise ValueError("title, proposer and details are required")
    return item


def _create_todo_item(payload):
    with TODO_LOCK:
        board = _todo_board_payload()
        item = _normalize_todo_item(payload)
        board["items"].insert(0, item)
        return _save_todo_board(board["items"])


def _update_todo_item(payload):
    if not isinstance(payload, dict):
        raise ValueError("todo payload must be an object")
    item_id = str(payload.get("id", "")).strip()
    if not item_id:
        raise ValueError("id is required")
    with TODO_LOCK:
        board = _todo_board_payload()
        for index, item in enumerate(board["items"]):
            if str(item.get("id")) == item_id:
                board["items"][index] = _normalize_todo_item(payload, existing=item)
                return _save_todo_board(board["items"])
    raise ValueError(f"todo item {item_id} not found")


def _dashboard_config():
    payload = _read_json_file(DASHBOARD_CONFIG_PATH, {})
    return payload if isinstance(payload, dict) else {}


def _effective_config():
    """The configuration a fresh process would load, as of right now.

    Deliberately *not* ``deepcopy(CONFIG)``. ``CONFIG`` is assembled once at
    import and ``settings/overrides.py`` already merges the override files
    into it, so it is a snapshot that goes stale the moment the dashboard
    writes one. Reading it back told a user who had just reset a key that it
    still held its old value — the exact "the edit looks like it worked"
    failure the 配置 panel exists to prevent — because the reset emptied the
    override file while the stale copy kept the overridden value.

    So rebuild from the Python defaults and re-apply the layers in the order
    ``overrides.apply_runtime_overrides`` uses (env last, twice, so it beats
    the environment file). The dashboard layer comes from
    ``_dashboard_config()`` rather than the loader's relative path, keeping
    the module path constants the single lever over where it reads.
    """
    from gaworld.settings.defaults import build_default_config
    from gaworld.settings.overrides import load_env_override, load_environment_config

    cfg = build_default_config()
    env_override = load_env_override()
    _deep_update(cfg, _dashboard_config())
    _deep_update(cfg, env_override)
    _deep_update(cfg, load_environment_config(cfg.get("environment_config_path")))
    _deep_update(cfg, env_override)
    return cfg


def _repo_path(value):
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    return (Path(REPO_ROOT) / path).resolve()


def _collaboration_config():
    config = _effective_config().get("collaboration", {})
    return config if isinstance(config, dict) else {}


def _get_collaboration_service():
    global _COLLABORATION_SERVICE
    with _COLLABORATION_LOCK:
        if _COLLABORATION_SERVICE is not None:
            return _COLLABORATION_SERVICE

        from gaworld.collaboration.service import CollaborationService
        from gaworld.llm.providers import call_llm
        from gaworld.memory.experience import append_agent_episode

        config = _effective_config()
        collaboration = config.get("collaboration", {})
        if not isinstance(collaboration, dict):
            collaboration = {}
        service = CollaborationService(
            config=collaboration,
            sessions_dir=_repo_path(
                collaboration.get(
                    "sessions_dir",
                    "output/collaboration/sessions",
                )
            ),
            memory_dir=_repo_path(
                config.get("memory_dir", "output/memory")
            ),
            agent_loader=lambda agent_id: _agent_detail(int(agent_id)),
            llm=call_llm,
            episode_writer=lambda agent_id, episode: append_agent_episode(
                agent_id,
                episode,
                cfg=config,
            ),
        )
        service.start()
        _COLLABORATION_SERVICE = service
        return service


def _reset_collaboration_service_for_tests():
    global _COLLABORATION_SERVICE
    with _COLLABORATION_LOCK:
        service = _COLLABORATION_SERVICE
        _COLLABORATION_SERVICE = None
    if service is not None:
        service.shutdown()


def _public_collaboration_session(payload):
    result = deepcopy(payload)
    result.pop("artifact_base_url", None)

    repo_root = Path(REPO_ROOT).resolve()
    collaboration = _collaboration_config()
    sessions_dir = _repo_path(
        collaboration.get(
            "sessions_dir",
            "output/collaboration/sessions",
        )
    )
    session_id = str(result.get("id") or "")
    safe_session_id = bool(
        session_id
        and session_id not in {".", ".."}
        and "/" not in session_id
        and "\\" not in session_id
        and all(
            ord(character) >= 32 and ord(character) != 127
            for character in session_id
        )
    )
    session_root = sessions_dir
    session_root_is_safe = False
    if safe_session_id:
        session_root = (sessions_dir / session_id).resolve()
        try:
            session_root.relative_to(sessions_dir)
        except ValueError:
            pass
        else:
            session_root_is_safe = True

    artifacts_root = (session_root / "artifacts").resolve()
    if session_root_is_safe:
        try:
            public_artifacts_root = artifacts_root.relative_to(repo_root)
        except ValueError:
            pass
        else:
            result["artifact_base_url"] = (
                "/" + public_artifacts_root.as_posix().rstrip("/") + "/"
            )

    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        return result

    public_artifacts = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        public_artifacts.append(artifact)
        artifact.pop("url", None)
        raw_path = str(artifact.get("path") or "")
        relative = Path(raw_path)
        if not raw_path or relative.is_absolute() or not session_root_is_safe:
            artifact.pop("path", None)
            continue
        resolved = (session_root / relative).resolve()
        try:
            resolved.relative_to(session_root)
        except ValueError:
            artifact.pop("path", None)
            continue
        try:
            public_path = resolved.relative_to(repo_root)
        except ValueError:
            continue
        artifact["url"] = "/" + public_path.as_posix()
    result["artifacts"] = public_artifacts
    return result


def _collaboration_agent_ids(payload):
    values = payload.get("agent_ids")
    if not isinstance(values, list):
        raise ValueError("agent_ids must be an array of integers")
    agent_ids = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("agent_ids must be an array of integers")
        agent_ids.append(value)
    return agent_ids


def _collaboration_integer(
    payload,
    field,
    *,
    default=None,
    allow_none=False,
):
    value = payload.get(field, default)
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _collaboration_roles(payload):
    roles = payload.get("role_overrides")
    if roles is None:
        return None
    if not isinstance(roles, dict):
        raise ValueError("role_overrides must be an object")
    normalized = {}
    for agent_id, role in roles.items():
        if (
            isinstance(agent_id, bool)
            or not isinstance(agent_id, (int, str))
            or not isinstance(role, str)
        ):
            raise ValueError(
                "role_overrides must map agent ids to role strings"
            )
        try:
            normalized[str(int(agent_id))] = role
        except ValueError as exc:
            raise ValueError(
                "role_overrides must map agent ids to role strings"
            ) from exc
    return normalized


def _collaboration_text(payload, field, *, default=""):
    value = payload.get(field, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


atexit.register(_reset_collaboration_service_for_tests)


def _provider_names(cfg):
    providers = cfg.get("llm", {}).get("providers", {})
    return sorted(providers.keys())


def _sim_start_date(cfg):
    from gaworld.sim._utils import _parse_sim_start_date

    calendar = cfg.get("calendar", {}) if isinstance(cfg.get("calendar"), dict) else {}
    return _parse_sim_start_date(calendar.get("start_date", "today"))


def _sim_span(cfg):
    """The run horizon expressed in the configured step unit.

    The toolbar shows one horizon field whose unit follows ``long_run.unit``,
    mirroring the CLI's ``--sim-days`` / ``--sim-months`` / ``--sim-years``.
    ``count`` is the number of steps the run actually plans, so a 3653-day
    year-unit run reads back as "10 年" rather than as a day count nobody
    typed.
    """
    from gaworld.sim._fastforward import long_run_unit, plan_horizon

    unit = long_run_unit(cfg)
    try:
        total_days = max(1, int(cfg.get("sim_days") or 1))
    except (TypeError, ValueError):
        total_days = 1
    periods = plan_horizon(1, total_days, unit, start_date=_sim_start_date(cfg))
    return {"unit": unit, "count": len(periods) or 1}


def _config_summary():
    cfg = _effective_config()
    routing = cfg.get("llm", {}).get("routing", {})
    return {
        "agent_ids": cfg.get("agent_ids", []),
        "sim_days": cfg.get("sim_days"),
        "sim_span": _sim_span(cfg),
        "seconds_per_day": cfg.get("seconds_per_day"),
        "simulate_realtime": cfg.get("simulate_realtime"),
        "time_step_minutes": cfg.get("time_step_minutes"),
        "long_run": cfg.get("long_run", {}),
        "routine_change": cfg.get("routine_change", {}),
        "calendar": cfg.get("calendar", {}),
        "llm": {
            "providers": _provider_names(cfg),
            "routing": routing,
        },
        "visualization": cfg.get("visualization", {}),
        "dashboard_config": _dashboard_config(),
        "city": _dashboard_config().get("city", ""),
        "cities": _city_choices(),
    }


def _city_choices():
    """Cities the run toolbar can switch between, cheapest-possible summary.

    Population is included because ``agent_ids`` is per-city: picking a city
    with fewer residents than the configured ids silently yields a run with
    nobody in it, and the operator needs to see the count to catch that.
    """
    try:
        from gaworld.city.bundle import list_cities

        return [
            {
                "slug": bundle.slug,
                "display_name": bundle.display_name,
                "population": bundle.population_count,
                "map_mode": bundle.map_mode,
            }
            for bundle in list_cities()
        ]
    except Exception as exc:  # the toolbar must load even if a bundle is broken
        _LOG.warning("city list unavailable: %s", exc)
        return []


def _sanitize_config_patch(payload):
    patch = {}
    for key in ("sim_days", "seconds_per_day"):
        if key in payload:
            patch[key] = max(1, int(payload[key]))
    # The toolbar sends the horizon in the step unit ("10 年"); the calendar
    # math that turns it into sim days lives in one place, so do it here
    # rather than approximating 30/365 in the browser. Wins over `sim_days`
    # when both are present.
    span = payload.get("sim_span")
    if isinstance(span, dict):
        from gaworld.sim._fastforward import span_days

        unit = str(span.get("unit") or "day").strip().lower()
        try:
            count = max(1, int(span.get("count") or 1))
        except (TypeError, ValueError):
            count = 1
        if unit in ("day", "month", "year"):
            patch["sim_days"] = span_days(
                unit, count, start_date=_sim_start_date(_effective_config())
            )
    if "agent_ids" in payload:
        ids = payload.get("agent_ids")
        if isinstance(ids, str):
            ids = [part.strip() for part in ids.split(",")]
        patch["agent_ids"] = [int(item) for item in ids if str(item).strip()]
    if "simulate_realtime" in payload:
        patch["simulate_realtime"] = bool(payload["simulate_realtime"])
    if "time_step_minutes" in payload:
        value = payload["time_step_minutes"]
        patch["time_step_minutes"] = None if value in ("", None, 0, "0") else value
    if isinstance(payload.get("long_run"), dict):
        lr = payload["long_run"]
        clean = {}
        if "enabled" in lr:
            clean["enabled"] = bool(lr["enabled"])
        if "brief_llm" in lr:
            clean["brief_llm"] = bool(lr["brief_llm"])
        if "unit" in lr:
            unit = str(lr["unit"] or "day").strip().lower()
            if unit in ("day", "month", "year"):
                clean["unit"] = unit
                # Picking 月/年 is picking fast-forward: there is no per-month
                # tick loop, so persisting "unit=year, enabled=false" would
                # save a config that silently runs 365 tick-loop days. Write
                # the combination the run will actually use, so the checkbox
                # reads back ticked instead of lying to the next visitor.
                if unit != "day":
                    clean["enabled"] = True
        if "max_state_delta" in lr:
            try:
                clean["max_state_delta"] = max(0.0, min(1.0, float(lr["max_state_delta"])))
            except (TypeError, ValueError):
                pass
        if "randomness" in lr:
            try:
                clean["randomness"] = max(0.0, min(1.0, float(lr["randomness"])))
            except (TypeError, ValueError):
                pass
        if "brief_max_chars" in lr:
            try:
                clean["brief_max_chars"] = max(40, int(lr["brief_max_chars"]))
            except (TypeError, ValueError):
                pass
        if clean:
            patch["long_run"] = clean
    if isinstance(payload.get("routine_change"), dict):
        rc = payload["routine_change"]
        clean = {}
        if "randomness" in rc:
            try:
                clean["randomness"] = max(0.0, min(1.0, float(rc["randomness"])))
            except (TypeError, ValueError):
                pass
        if clean:
            patch["routine_change"] = clean
    if isinstance(payload.get("calendar"), dict):
        patch["calendar"] = payload["calendar"]
    if isinstance(payload.get("llm"), dict):
        llm = payload["llm"]
        routing = llm.get("routing", {})
        if isinstance(routing, dict):
            patch.setdefault("llm", {})["routing"] = routing
    if "city" in payload:
        patch["city"] = _validated_city(payload["city"])
    return patch


def _validated_city(value):
    """Resolve a city reference to its slug; "" means the default world.

    An unresolvable slug is rejected loudly. Writing it through would leave the
    config pointing at a city that does not exist, and ``apply_city`` degrades
    silently to the default world — so the run would quietly happen somewhere
    other than where the operator asked.
    """
    ref = str(value or "").strip()
    if not ref:
        return ""
    from gaworld.city.bundle import CityNotFoundError, resolve_city

    try:
        return resolve_city(ref).slug
    except CityNotFoundError as exc:
        raise ValueError(f"未知城市 {ref!r}：{exc}") from exc


def _save_config_patch(payload):
    current = _dashboard_config()
    patch = _sanitize_config_patch(payload)
    _deep_update(current, patch)
    _atomic_write_json(DASHBOARD_CONFIG_PATH, current)
    return _config_summary()


def _profile_sections():
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "", []
    matches = list(PROFILE_HEADER_RE.finditer(text))
    sections = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append({
            "id": int(match.group(1)),
            "name": match.group(2).strip(),
            "start": start,
            "end": end,
            "text": text[start:end].strip() + "\n",
        })
    return text, sections


def _agents_summary():
    _, sections = _profile_sections()
    configured = set(int(item) for item in _effective_config().get("agent_ids", []))
    return [
        {
            "id": section["id"],
            "name": section["name"],
            "configured": section["id"] in configured,
        }
        for section in sections
    ]


def _agent_profile(agent_id):
    _, sections = _profile_sections()
    for section in sections:
        if section["id"] == int(agent_id):
            return section
    return None


def _save_agent_profile(agent_id, profile_text):
    full_text, sections = _profile_sections()
    target = None
    for section in sections:
        if section["id"] == int(agent_id):
            target = section
            break
    if not target:
        raise ValueError(f"Profile {agent_id} not found")
    new_block = str(profile_text).strip() + "\n\n"
    updated = full_text[:target["start"]] + new_block + full_text[target["end"]:]
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        f.write(updated)
    return _agent_profile(agent_id)


# ---------------------------------------------------------------------------
# Agent state (CSV seed) read / write, skills, finance, and agent creation.
# The CSV is the machine-readable seed the simulator loads; the Markdown
# profile is the narrative twin. Studio edits go to the CSV for state vars and
# to the profile block for narrative, mirroring how imported agents are stored.
# ---------------------------------------------------------------------------

def _read_state_rows():
    if not os.path.exists(STATE_CSV_PATH):
        return [], []
    with open(STATE_CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def _row_id(row):
    try:
        return int(float(row.get("id")))
    except (TypeError, ValueError):
        return None


def _num(value, default=0.5):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _state_row_to_payload(row):
    try:
        age = int(float(row.get("age")))
    except (TypeError, ValueError):
        age = None
    return {
        "id": _row_id(row),
        "name": (row.get("name") or "").strip(),
        "gender": (row.get("gender") or "").strip(),
        "age": age,
        "hukou": (row.get("hukou") or "").strip(),
        "residence": (row.get("residence") or "").strip(),
        "state": {key: _num(row.get(key)) for key in STATE_VAR_KEYS},
    }


def _agent_state(agent_id):
    _, rows = _read_state_rows()
    for row in rows:
        if _row_id(row) == int(agent_id):
            return _state_row_to_payload(row)
    return None


def _atomic_write_state(fieldnames, rows):
    tmp_path = STATE_CSV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    os.replace(tmp_path, STATE_CSV_PATH)


def _save_agent_state(agent_id, payload):
    fieldnames, rows = _read_state_rows()
    if not fieldnames:
        raise ValueError("State CSV is missing or empty")
    target = next((row for row in rows if _row_id(row) == int(agent_id)), None)
    if target is None:
        raise ValueError(f"Agent {agent_id} not found in state CSV")
    for key in ("name", "gender", "hukou", "residence"):
        if payload.get(key) not in (None, ""):
            target[key] = str(payload[key])
    if payload.get("age") not in (None, ""):
        target["age"] = str(int(payload["age"]))
    incoming = payload.get("state") or {}
    for key in STATE_VAR_KEYS:
        if incoming.get(key) is not None:
            target[key] = round(max(0.0, min(1.0, float(incoming[key]))), 4)
    _atomic_write_state(fieldnames, rows)
    result = _agent_state(agent_id)
    try:
        _sync_profile_state_lines(agent_id, result["state"])
    except Exception:  # noqa: BLE001 - narrative sync is best-effort, never blocks the CSV write
        _LOG.exception("profile state sync failed for agent %s", agent_id)
    return result


def _sync_profile_state_lines(agent_id, state):
    """Mirror the CSV state onto the profile Markdown so the two don't drift.

    The CSV is authoritative. This rewrites only the two structured lines a
    profile block carries — the ``**研究增强变量初始化**`` bullets and the
    ``**核心状态变量**`` summary — leaving all narrative prose untouched. If a
    profile lacks those lines, nothing is changed.
    """
    section = _agent_profile(agent_id)
    if not section:
        return
    text = section["text"]
    core = (
        f"**核心状态变量**：emotion {state['emotion']:.2f}｜stress {state['stress']:.2f}｜"
        f"econ_security {state['econ_security']:.2f}｜city_identity {state['city_identity']:.2f}"
    )
    new_text = re.sub(r"\*\*核心状态变量\*\*：.*", core, text)
    for key in ("policy_sensitivity", "platform_dependence", "risk_preference", "voice_propensity", "mobility_intent"):
        new_text = re.sub(rf"^- {key}：.*$", f"- {key}：{state[key]:.2f}", new_text, flags=re.MULTILINE)
    if new_text != text:
        _save_agent_profile(agent_id, new_text)


def _memory_base_dir():
    return os.path.join(REPO_ROOT, _effective_config().get("memory_dir", "output/memory"))


def _memory_file(agent_id, suffix=""):
    return os.path.join(_memory_base_dir(), f"agent_{int(agent_id)}{suffix}.json")


def _social_snapshot(agent_id):
    rels = _read_json_file(_memory_file(agent_id, "_relationships"), {})
    if not isinstance(rels, dict) or not rels:
        return None
    tier_counts = {"inner": 0, "close": 0, "acquaintance": 0, "weak": 0}
    relations = []
    for key, item in rels.items():
        if not isinstance(item, dict):
            continue
        tier = item.get("dunbar_tier") or ""
        if tier in tier_counts:
            tier_counts[tier] += 1
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        relations.append({
            "id": key,
            "name": profile.get("name") or str(key),
            "role": item.get("role") or "",
            "kind": item.get("kind") or "agent",
            "tier": tier,
            "closeness": _num(item.get("closeness"), 0.0),
            "trust": _num(item.get("trust"), 0.0),
        })
    relations.sort(key=lambda r: r["closeness"], reverse=True)
    return {"count": len(relations), "tier_counts": tier_counts, "relations": relations[:40]}


DUNBAR_TIER_KEYS = ("inner", "close", "acquaintance", "weak")

# Shape a manually added tie starts from. The simulator's own relationship
# schema (gaworld/social/network.py) fills the rest on first load; these are
# the fields a hand-authored edge needs to be usable straight away.
_MANUAL_RELATION_DEFAULTS = {
    "kind": "ghost",
    "tie_origin": "manual",
    "channels": ["chat"],
    "obligation": 0.4,
    "obligation_base": 0.4,
    "friction": 0.2,
    "decay_rate": 0.002,
    "last_interaction_day": 0,
    "last_contact_day": 0,
    "dunbar_tier": "acquaintance",
}


def _new_relation_key(rels):
    index = 1
    while f"manual_{index}" in rels:
        index += 1
    return f"manual_{index}"


def _save_agent_relationships(agent_id, payload):
    """Upsert / remove relationship edges edited in the Studio.

    Only the fields the UI exposes (name / role / tier / closeness / trust)
    are touched; every other key the simulator wrote — friction, channels,
    interaction days — is preserved on existing edges. ``relations`` upserts,
    ``removed`` deletes; ties outside the snapshot's top-40 window are left
    alone because neither list mentions them.
    """
    path = _memory_file(agent_id, "_relationships")
    rels = _read_json_file(path, {})
    if not isinstance(rels, dict):
        rels = {}
    for key in payload.get("removed") or []:
        rels.pop(str(key), None)
    for item in payload.get("relations") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip() or _new_relation_key(rels)
        entry = rels.get(key)
        if not isinstance(entry, dict):
            entry = deepcopy(_MANUAL_RELATION_DEFAULTS)
            rels[key] = entry
        profile = entry.get("profile")
        if not isinstance(profile, dict):
            profile = {}
            entry["profile"] = profile
        name = str(item.get("name") or "").strip()
        if name:
            profile["name"] = name
        role = str(item.get("role") or "").strip()
        if role:
            entry["role"] = role
        if item.get("tier") in DUNBAR_TIER_KEYS:
            entry["dunbar_tier"] = item["tier"]
        for field in ("closeness", "trust"):
            if item.get(field) is not None:
                entry[field] = round(max(0.0, min(1.0, float(item[field]))), 4)
    _atomic_write_json(path, rels)
    return _social_snapshot(agent_id) or {"count": 0, "tier_counts": {}, "relations": []}


def _scan_skill_dir(directory):
    items = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".md"):
                continue
            title = name[:-3]
            try:
                with open(os.path.join(directory, name), "r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped.startswith("#"):
                            title = stripped.lstrip("#").strip() or title
                            break
            except OSError:
                pass
            items.append({"file": name, "title": title})
    return items


def _skills_library():
    return _scan_skill_dir(SKILLS_DIR)


def _private_skills(agent_id):
    # Mirrors SkillRegistry._private_dir: {memory_dir}/agent_{id}_skills
    memory_dir = _effective_config().get("memory_dir", "output/memory")
    return _scan_skill_dir(os.path.join(REPO_ROOT, memory_dir, f"agent_{int(agent_id)}_skills"))


def _capabilities_snapshot(agent_id):
    data = _read_json_file(CAPABILITIES_CACHE_PATH, {})
    if not isinstance(data, dict):
        return None
    entry = data.get(str(int(agent_id)))
    return entry if isinstance(entry, dict) else None


def _rag_snapshot(memory_items):
    # External-RAG memories are tagged with the [额外信息…] prefix (gaworld/sim/_rag.py).
    items = []
    for item in memory_items if isinstance(memory_items, list) else []:
        text = str(item).strip()
        if text.startswith("[额外信息"):
            items.append(text[:300])
    return {"count": len(items), "items": items[:20]}


# --- Memory content (Studio step 4) -----------------------------------------
# The counts alone don't say what an agent actually remembers, so the Studio
# also reads the memory bodies. Lists are capped to keep the detail payload —
# which the collaboration service reuses per LLM turn — from ballooning.

RAG_TAG_PREFIX = "[额外信息"
MANUAL_RAG_PREFIX = "[额外信息 | 来源:manual] "
MEMORY_TEXT_MAX_CHARS = 600
MEMORY_LIST_LIMIT = 300


def _memory_items(memory):
    rows = []
    for index, raw in enumerate(memory if isinstance(memory, list) else []):
        text = str(raw).strip()
        if not text:
            continue
        rows.append({
            "index": index,
            "text": text[:MEMORY_TEXT_MAX_CHARS],
            "rag": text.startswith(RAG_TAG_PREFIX),
        })
    return rows[-MEMORY_LIST_LIMIT:]


def _habit_rows(habits):
    """Flatten the ``{phase}|{scope}|{activity}`` habit map into sorted rows."""
    rows = []
    for key, item in (habits.items() if isinstance(habits, dict) else []):
        if not isinstance(item, dict):
            continue
        parts = str(key).split("|")
        rows.append({
            "key": str(key),
            "phase": parts[0] if parts else "",
            "activity": parts[-1] if len(parts) > 1 else "",
            "preferred_action": str(item.get("preferred_action") or ""),
            "strength": _num(item.get("strength"), 0.0),
            "last_updated_day": item.get("last_updated_day"),
        })
    rows.sort(key=lambda row: row["strength"], reverse=True)
    return rows[:60]


def _schedule_rows(schedule):
    rows = []
    for item in schedule if isinstance(schedule, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "time": str(item.get("time") or ""),
            "activity": str(item.get("activity") or ""),
        })
    return rows[:80]


def _memory_detail(memory):
    intentions = memory.get("intentions")
    return {
        "long_term": _memory_items(memory.get("memory")),
        "habits": _habit_rows(memory.get("habits")),
        "intentions": intentions if isinstance(intentions, dict) else {},
        "schedule": _schedule_rows(memory.get("schedule")),
    }


def _index_memory_entry(agent_id, text):
    """Mirror a hand-added memory into the vector DB when one is already built.

    When the DB has no rows for this agent yet the simulator seeds it from the
    JSON file on its next start, so writing here would be redundant. Failures
    are swallowed: the JSON file is the source of truth and must not be held
    hostage to an embedding backend.
    """
    try:
        from gaworld.memory.store import vector_db_add_entry, vector_db_count_entries

        if vector_db_count_entries(int(agent_id)) > 0:
            vector_db_add_entry(int(agent_id), "memory", text)
    except Exception:  # noqa: BLE001 - best-effort index, never blocks the write
        _LOG.exception("vector index failed for agent %s", agent_id)


def _append_agent_memory(agent_id, payload):
    """Append one hand-written long-term memory or RAG snippet."""
    kind = str(payload.get("kind") or "memory").strip().lower()
    if kind not in ("memory", "rag"):
        raise ValueError("kind must be 'memory' or 'rag'")
    text = re.sub(r"\s+", " ", str(payload.get("text") or "")).strip()
    if not text:
        raise ValueError("text is required")
    text = text[:MEMORY_TEXT_MAX_CHARS]
    if kind == "rag" and not text.startswith(RAG_TAG_PREFIX):
        text = MANUAL_RAG_PREFIX + text
    path = _memory_file(agent_id)
    items = _read_json_file(path, [])
    if not isinstance(items, list):
        items = []
    items.append(text)
    _atomic_write_json(path, items)
    _index_memory_entry(agent_id, text)
    return {
        "kind": kind,
        "text": text,
        "count": len(items),
        "long_term": _memory_items(items),
        "rag": _rag_snapshot(items),
    }


# --- Finance (Studio step 7) ------------------------------------------------
# The per-agent economy JSON is the simulator's live state and is reloaded on
# the next stateful run, so that is what the Studio edits. The wealth snapshot
# CSV is a run artifact — readable, but not a place to write back into.

FINANCE_ACCOUNT_KEYS = ("checking", "savings", "investment", "housing_fund")
FINANCE_AMOUNT_KEYS = ("debt", "gross_monthly_salary", "net_monthly_salary", "monthly_rent")
FINANCE_RATE_KEYS = ("engel_coefficient", "savings_rate")
# Liquid accounts only — mirrors _total_balance in gaworld/economy/finance.py.
FINANCE_LIQUID_KEYS = ("checking", "savings", "investment")


def _agent_finance(agent_id):
    econ = _read_json_file(_memory_file(agent_id, "_economy"), {})
    if isinstance(econ, dict) and econ:
        accounts = econ.get("accounts") if isinstance(econ.get("accounts"), dict) else {}
        payload = {
            "source": "state",
            "editable": True,
            "currency": str(econ.get("currency") or "CNY"),
            "accounts": {key: _num(accounts.get(key), 0.0) for key in FINANCE_ACCOUNT_KEYS},
            "balance": _num(econ.get("balance"), 0.0),
        }
        payload.update({key: _num(econ.get(key), 0.0) for key in FINANCE_AMOUNT_KEYS})
        payload.update({key: _num(econ.get(key), 0.0) for key in FINANCE_RATE_KEYS})
        return payload
    row = _finance_snapshot(agent_id)
    if not row:
        return None
    payload = {
        "source": "snapshot",
        "editable": False,
        "currency": str(row.get("currency") or "CNY"),
        "accounts": {key: _num(row.get(key), 0.0) for key in FINANCE_ACCOUNT_KEYS},
        "balance": _num(row.get("balance"), 0.0),
    }
    payload.update({key: _num(row.get(key), 0.0) for key in FINANCE_AMOUNT_KEYS})
    payload.update({key: _num(row.get(key), 0.0) for key in FINANCE_RATE_KEYS})
    return payload


def _save_agent_finance(agent_id, payload):
    path = _memory_file(agent_id, "_economy")
    econ = _read_json_file(path, {})
    if not isinstance(econ, dict) or not econ:
        raise ValueError("No economy state for this agent yet — run the simulation once first")
    accounts = econ.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        econ["accounts"] = accounts
    incoming = payload.get("accounts") if isinstance(payload.get("accounts"), dict) else {}
    for key in FINANCE_ACCOUNT_KEYS:
        if incoming.get(key) is not None:
            accounts[key] = round(max(0.0, float(incoming[key])), 2)
    for key in FINANCE_AMOUNT_KEYS:
        if payload.get(key) is not None:
            econ[key] = round(max(0.0, float(payload[key])), 2)
    for key in FINANCE_RATE_KEYS:
        if payload.get(key) is not None:
            econ[key] = round(max(0.0, min(1.0, float(payload[key]))), 4)
    econ["balance"] = round(sum(_num(accounts.get(key), 0.0) for key in FINANCE_LIQUID_KEYS), 2)
    _atomic_write_json(path, econ)
    return _agent_finance(agent_id)


def _growth_snapshot(agent_id):
    from gaworld.interests import load_agent_growth_profile

    memory_dir = os.path.join(REPO_ROOT, _effective_config().get("memory_dir", "output/memory"))
    profile = load_agent_growth_profile(int(agent_id), memory_dir)
    return profile or None


def _openclaw_snapshot(agent_id):
    cfg = CONFIG.get("openclaw", {}) or {}
    state = _read_json_file(RELAY_STATE_PATH, {})
    directory = state.get("directory") if isinstance(state, dict) else {}
    directory = directory if isinstance(directory, dict) else {}

    entry = None
    openclaw_ids = set()
    for cluster, cluster_map in directory.items():
        if not isinstance(cluster_map, dict):
            continue
        for aid, item in cluster_map.items():
            if not isinstance(item, dict):
                continue
            if item.get("agent_type") == "openclaw":
                openclaw_ids.add(str(aid))
            if str(aid) == str(int(agent_id)) and entry is None:
                entry = {**item, "cluster": cluster}

    sent = received = 0
    messages = state.get("messages") if isinstance(state, dict) else []
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict):
            continue
        frm, to = str(msg.get("from_agent")), str(msg.get("to_agent"))
        if frm == str(int(agent_id)) and to in openclaw_ids:
            sent += 1
        elif to == str(int(agent_id)) and frm in openclaw_ids:
            received += 1

    is_openclaw = bool(entry and entry.get("agent_type") == "openclaw")
    return {
        "enabled": bool(cfg.get("enabled")),
        "registered": entry is not None,
        "is_openclaw_agent": is_openclaw,
        "cluster": entry.get("cluster") if entry else None,
        "node_id": entry.get("node_id") if entry else None,
        "messages_sent": sent,
        "messages_received": received,
        "connected": is_openclaw or (sent + received) > 0,
    }


def _cognition_snapshot(capabilities, growth, memory_counts, rag):
    """Derived cognitive index — NOT a measured IQ.

    Transparent composite of what the simulation actually tracks:
    skill breadth, deliverable capacity, growth levels, memory volume,
    and external (RAG) knowledge, mapped onto a familiar 60–140 scale.
    """
    caps = capabilities or {}
    growth_items = (growth or {}).get("items", []) or []
    avg_level = (
        sum(_num(item.get("level"), 0.0) for item in growth_items) / len(growth_items)
        if growth_items else 0.0
    )
    memory_total = sum(v for v in memory_counts.values() if isinstance(v, (int, float)))
    components = {
        "skill_breadth": min(1.0, len(caps.get("skills") or []) / 6.0),
        "deliverable_capacity": min(1.0, len(caps.get("deliverables") or []) / 4.0),
        "growth_level": avg_level,
        "memory_volume": min(1.0, memory_total / 200.0),
        "external_knowledge": min(1.0, rag.get("count", 0) / 10.0),
    }
    weights = {
        "skill_breadth": 0.25,
        "deliverable_capacity": 0.15,
        "growth_level": 0.25,
        "memory_volume": 0.2,
        "external_knowledge": 0.15,
    }
    score01 = sum(components[key] * weights[key] for key in weights)
    return {
        "score": round(60 + score01 * 80),
        "score01": round(score01, 4),
        "components": {key: round(value, 4) for key, value in components.items()},
    }


def _agent_card(identity, capabilities, private_skills, growth, openclaw):
    caps = capabilities or {}
    skills = list(caps.get("skills") or [])
    for skill in private_skills:
        if skill["title"] not in skills:
            skills.append(skill["title"])
    interests = list(caps.get("interests") or [])
    for item in (growth or {}).get("items", []) or []:
        name = item.get("name")
        if name and name not in interests:
            interests.append(name)
    return {
        "schema": "gaworld.agent-card/v1",
        "id": identity["id"],
        "name": identity["name"],
        "description": " · ".join(
            str(part) for part in (identity.get("gender"), f"{identity.get('age')}岁", identity.get("residence")) if part
        ),
        "job_label": caps.get("job_label") or "",
        "skills": skills,
        "interests": interests,
        "deliverables": list(caps.get("deliverables") or []),
        "adapters": list(caps.get("adapter_priority") or []),
        "openclaw_connected": bool(openclaw.get("connected")),
        "endpoints": {
            "detail": f"/api/agents/{identity['id']}/detail",
            "interview": "/api/interview",
        },
    }


def _finance_snapshot(agent_id):
    if not os.path.exists(ECONOMY_SNAPSHOT_PATH):
        return None
    try:
        with open(ECONOMY_SNAPSHOT_PATH, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    if int(float(row.get("agent_id"))) == int(agent_id):
                        return dict(row)
                except (TypeError, ValueError):
                    continue
    except OSError:
        return None
    return None


# ---------------------------------------------------------------------------
# Big Five (OCEAN) seed scores — studio panel, step 2.
# ---------------------------------------------------------------------------

#: Where the plugin reads the frozen z scores from. Editing here takes effect on
#: the **next** run, like every other seed the studio writes: the plugin loads
#: this file once at ``agents.built`` and the record is read-only afterwards.
BIG5_CSV_PATH = os.path.join(
    REPO_ROOT,
    (CONFIG.get("personality", {}) or {}).get("profile_path", "data/agents_big5.csv"),
)

#: The generator's authoring floor. A dimension at or above this was written
#: into the resident's 人格与行为倾向 paragraph; below it the paragraph is
#: silent. This one rule is the whole basis of the consistency flags below --
#: they are arithmetic on the scores, **not** an analysis of the text.
BIG5_AUTHORING_FLOOR = 0.5

#: Snapshot column: the five values the paragraph was authored from. Without it
#: the baseline is destroyed by the first edit and the contradiction becomes
#: invisible on reload -- which is the failure the panel exists to prevent.
BIG5_AUTHORED_COLUMN = "authored_z"

BIG5_DIMENSIONS = ("o", "c", "e", "a", "n")

#: Shown beside each slider so the reader knows what to look for in the
#: paragraph. Same wording as ``scripts/calibrate_big5.py``'s anchors, so the
#: panel and the calibrator describe the same poles.
BIG5_POLES = {
    "o": ("只走熟悉的路线、认准的做法很少改", "主动找新鲜事物、爱试没试过的做法"),
    "c": ("计划容易落空、事情往后拖", "提前排好顺序、被打断也会补回来"),
    "e": ("回避热闹场合、独处恢复精力", "主动搭话、独处久了会闷"),
    "a": ("说话直接、不太迁就别人", "先替别人考虑、难以拒绝"),
    "n": ("情绪很稳、别人急他不急", "容易往坏处想、情绪起落大"),
}

BIG5_NAMES_ZH = {
    "o": "开放性", "c": "尽责性", "e": "外向性", "a": "宜人性", "n": "神经质",
}

#: English twins, shipped alongside so the studio panel can label the sliders
#: in either language. Same approach as the config docs: both languages travel
#: in the payload and the client picks, rather than the server guessing from an
#: Accept-Language header the dashboard never sets.
BIG5_POLES_EN = {
    "o": ("sticks to familiar routes, rarely changes a settled approach",
          "seeks out what is new, likes trying what they have not tried"),
    "c": ("plans slip, things get put off",
          "orders things in advance, picks them back up after an interruption"),
    "e": ("avoids crowded occasions, recovers energy alone",
          "starts conversations, gets restless alone for long"),
    "a": ("speaks directly, does not bend much for others",
          "thinks of others first, finds it hard to refuse"),
    "n": ("steady, unhurried when others panic",
          "assumes the worst, large swings of mood"),
}

BIG5_NAMES_EN = {
    "o": "Openness", "c": "Conscientiousness", "e": "Extraversion",
    "a": "Agreeableness", "n": "Neuroticism",
}


def _read_big5_rows():
    if not os.path.exists(BIG5_CSV_PATH):
        return [], []
    with open(BIG5_CSV_PATH, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _parse_authored(raw):
    """``"o=-0.35;c=0.48;..."`` -> dict, tolerating a missing or broken value."""
    out = {}
    for chunk in str(raw or "").split(";"):
        key, _, value = chunk.partition("=")
        key = key.strip()
        if key in BIG5_DIMENSIONS:
            try:
                out[key] = round(float(value), 4)
            except (TypeError, ValueError):
                continue
    return out


def _format_authored(values):
    return ";".join(f"{dim}={values.get(dim, 0.0):.4f}" for dim in BIG5_DIMENSIONS)


def _big5_paragraph(agent_id):
    section = _agent_profile(agent_id)
    if not section:
        return ""
    match = re.search(r"\*\*人格与行为倾向\*\*：(.+)", section.get("text", "") or "")
    return match.group(1).strip() if match else ""


def _big5_consistency(current, authored, paragraph):
    """Per-dimension flags for "does the paragraph still describe this?".

    Derived from one rule -- the generator wrote a dimension into the paragraph
    iff ``|z| >= BIG5_AUTHORING_FLOOR`` -- applied to the value the paragraph
    was authored from versus the value now. **No keyword matching.** A keyword
    probe on this corpus already misled once (the personality proposal records
    an E probe reading -0.13 because the word list used topic nouns rather than
    valence-bearing phrases), and a wrong-but-confident indicator here would be
    worse than none: the operator would trust it instead of reading.

    * ``rewrite``      -- the paragraph describes this dimension and the score
      moved away from what it describes. ``severity: "flip"`` when the sign
      changed, which is a guaranteed contradiction rather than a drift.
    * ``now_missing``  -- the paragraph is silent here and the score is now
      distinctive, so the text under-describes the resident.
    * ``now_moot``     -- the paragraph describes a pole the resident no longer
      has, so the text over-describes them.
    * ``ok``           -- nothing to do.
    """
    flags = {}
    for dim in BIG5_DIMENSIONS:
        now = float(current.get(dim, 0.0))
        was = authored.get(dim)
        was_written = was is not None and abs(was) >= BIG5_AUTHORING_FLOOR
        is_written = abs(now) >= BIG5_AUTHORING_FLOOR
        state, severity = "ok", ""
        if was is None:
            state = "unknown"
        elif was_written and is_written:
            if (now > 0) != (was > 0):
                state, severity = "rewrite", "flip"
            elif abs(now - was) >= BIG5_AUTHORING_FLOOR:
                state, severity = "rewrite", "drift"
        elif was_written and not is_written:
            state = "now_moot"
        elif not was_written and is_written:
            state = "now_missing"
        flags[dim] = {
            "state": state,
            "severity": severity,
            "authored": was,
            "current": round(now, 4),
            "written_in_paragraph": was_written,
        }
    return flags


def _agent_big5(agent_id):
    _, rows = _read_big5_rows()
    target = next((r for r in rows if _row_id(r) == int(agent_id)), None)
    if target is None:
        return None
    values = {}
    for dim in BIG5_DIMENSIONS:
        try:
            values[dim] = round(float(target.get(dim) or 0.0), 4)
        except (TypeError, ValueError):
            values[dim] = 0.0
    authored = _parse_authored(target.get(BIG5_AUTHORED_COLUMN))
    if not authored and str(target.get("source", "")).strip() == "sampled_authored":
        # Never hand-edited: the values on disk *are* what the paragraph was
        # written from, so they are the baseline.
        authored = dict(values)
    paragraph = _big5_paragraph(agent_id)
    return {
        "id": int(agent_id),
        "name": target.get("name", ""),
        "values": values,
        "authored": authored,
        "source": target.get("source", ""),
        "paragraph": paragraph,
        "consistency": _big5_consistency(values, authored, paragraph),
        "poles": BIG5_POLES,
        "names": BIG5_NAMES_ZH,
        "poles_en": BIG5_POLES_EN,
        "names_en": BIG5_NAMES_EN,
        "floor": BIG5_AUTHORING_FLOOR,
        "clip": 2.5,
    }


def _save_agent_big5(agent_id, payload):
    """Write the five z scores back to the seed CSV.

    Three things happen besides the numbers:

    * ``source`` becomes ``hand_edited`` so a later run is not attributed to the
      sampler that no longer produced these values;
    * the authored baseline is snapshotted on the first edit, so the paragraph
      comparison survives reloads;
    * ``redundant`` is cleared, because it was the verdict of a collinearity
      gate run against values that have just changed.
    """
    fieldnames, rows = _read_big5_rows()
    if not fieldnames:
        raise ValueError("Big Five CSV is missing or empty")
    target = next((r for r in rows if _row_id(r) == int(agent_id)), None)
    if target is None:
        raise ValueError(f"Agent {agent_id} not found in {os.path.basename(BIG5_CSV_PATH)}")

    if BIG5_AUTHORED_COLUMN not in fieldnames:
        fieldnames = list(fieldnames) + [BIG5_AUTHORED_COLUMN]
    if not str(target.get(BIG5_AUTHORED_COLUMN, "")).strip():
        baseline = {}
        for dim in BIG5_DIMENSIONS:
            try:
                baseline[dim] = round(float(target.get(dim) or 0.0), 4)
            except (TypeError, ValueError):
                baseline[dim] = 0.0
        target[BIG5_AUTHORED_COLUMN] = _format_authored(baseline)

    incoming = payload.get("values") or {}
    changed = False
    for dim in BIG5_DIMENSIONS:
        if incoming.get(dim) is None:
            continue
        try:
            value = float(incoming[dim])
        except (TypeError, ValueError):
            raise ValueError(f"{dim} is not a number") from None
        if not math.isfinite(value):
            raise ValueError(f"{dim} is not finite")
        value = round(max(-2.5, min(2.5, value)), 4)
        if str(target.get(dim, "")) != str(value):
            changed = True
        target[dim] = value
    if changed:
        target["source"] = "hand_edited"
        if "redundant" in fieldnames:
            target["redundant"] = ""

    tmp_path = BIG5_CSV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    os.replace(tmp_path, BIG5_CSV_PATH)
    return _agent_big5(agent_id)


def _agent_detail(agent_id):
    state = _agent_state(agent_id)
    if state is None:
        return None
    profile = _agent_profile(agent_id) or {}
    memory = _memory_payload(agent_id)

    def _count(value):
        return len(value) if isinstance(value, (list, dict)) else 0

    identity = {
        "id": state["id"],
        "name": state["name"],
        "gender": state["gender"],
        "age": state["age"],
        "hukou": state["hukou"],
        "residence": state["residence"],
    }
    memory_counts = {
        "long_term": _count(memory.get("memory")),
        "habits": _count(memory.get("habits")),
        "intentions": _count(memory.get("intentions")),
        "schedule": _count(memory.get("schedule")),
    }
    capabilities = _capabilities_snapshot(agent_id)
    private_skills = _private_skills(agent_id)
    growth = _growth_snapshot(agent_id)
    rag = _rag_snapshot(memory.get("memory"))
    openclaw = _openclaw_snapshot(agent_id)
    return {
        "identity": identity,
        "state": state["state"],
        "profile_text": profile.get("text", ""),
        "memory_counts": memory_counts,
        "memory": _memory_detail(memory),
        "finance": _finance_snapshot(agent_id),
        "finance_state": _agent_finance(agent_id),
        "social": _social_snapshot(agent_id),
        "skills": _skills_library(),
        "private_skills": private_skills,
        "capabilities": capabilities,
        "growth": growth,
        "goals": memory.get("goals", {}),
        "rag": rag,
        "openclaw": openclaw,
        "cognition": _cognition_snapshot(capabilities, growth, memory_counts, rag),
        "agent_card": _agent_card(identity, capabilities, private_skills, growth, openclaw),
    }


def _next_agent_id():
    _, rows = _read_state_rows()
    ids = [rid for rid in (_row_id(row) for row in rows) if rid is not None]
    _, sections = _profile_sections()
    ids.extend(section["id"] for section in sections)
    return (max(ids) + 1) if ids else 1


def _create_agent(payload):
    from gaworld.sim.agents_loader import _clip_state_value, _format_imported_profile_block

    agent_id = _next_agent_id()
    state_in = payload.get("state") or {}
    defaults = {
        "emotion": 0.55,
        "stress": 0.5,
        "econ_security": 0.5,
        "city_identity": 0.5,
        "policy_sensitivity": 0.5,
        "platform_dependence": 0.5,
        "risk_preference": 0.5,
        "voice_propensity": 0.5,
        "mobility_intent": 0.5,
    }
    state = {key: _clip_state_value(state_in.get(key), defaults[key]) for key in STATE_VAR_KEYS}
    profile_payload = {
        "name": str(payload.get("name") or f"新智能体{agent_id}"),
        "gender": str(payload.get("gender") or "未知"),
        "age": int(payload.get("age") or 30),
        "hukou": str(payload.get("hukou") or "未知"),
        "residence": str(payload.get("residence") or "杭州"),
        "job": str(payload.get("job") or "待补充"),
        "personality": str(payload.get("personality") or "待补充"),
        "daily_life": str(payload.get("daily_life") or "待补充"),
        "values": str(payload.get("values") or "待补充"),
        "education_income": str(payload.get("education_income") or "待补充"),
        "social_network": str(payload.get("social_network") or "待补充"),
        "state": state,
    }
    fieldnames, rows = _read_state_rows()
    if not fieldnames:
        raise ValueError("State CSV is missing or empty")
    new_row = {
        "id": agent_id,
        "name": profile_payload["name"],
        "gender": profile_payload["gender"],
        "age": profile_payload["age"],
        "hukou": profile_payload["hukou"],
        "residence": profile_payload["residence"],
    }
    new_row.update({key: state[key] for key in STATE_VAR_KEYS})
    rows.append({key: new_row.get(key, "") for key in fieldnames})
    _atomic_write_state(fieldnames, rows)

    with open(PROFILE_PATH, "a", encoding="utf-8") as f:
        f.write(_format_imported_profile_block(agent_id, profile_payload))

    return {"id": agent_id, "name": profile_payload["name"], "state": _agent_state(agent_id)}


def _tail_text(path, max_chars=12000):
    if not os.path.exists(path):
        return ""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - max_chars))
        data = f.read()
    return data.decode("utf-8", errors="replace")


def _decode_log_bytes(data, aligned):
    """Decode a run-log slice without splitting a multi-byte UTF-8 character.

    Returns ``(text, consumed)``: `consumed` counts the bytes the text covers
    (including any dropped leading fragment) so the caller can keep the next
    read starting on a character boundary. `aligned` says the slice already
    starts on one, which is true for every incremental read.
    """
    skipped = 0
    if not aligned:
        while skipped < len(data) and 0x80 <= data[skipped] < 0xC0:
            skipped += 1
        data = data[skipped:]
    pending = 0
    for back in range(1, min(4, len(data)) + 1):
        byte = data[-back]
        if byte < 0x80:
            break
        if byte >= 0xC0:
            width = 2 if byte < 0xE0 else 3 if byte < 0xF0 else 4
            if back < width:
                pending = back
            break
    if pending:
        data = data[:-pending]
    return data.decode("utf-8", errors="replace"), skipped + len(data)


def _run_log_slice(path, offset=None):
    """Read the run log from `offset`, or its tail when `offset` is unusable.

    The browser polls status every couple of seconds, so it sends the offset it
    already has and only receives what was appended since — that is what lets
    the panel hold the entire log instead of a trailing window.
    """
    if not os.path.exists(path):
        return {"text": "", "append": False, "offset": 0, "size": 0, "skipped": 0}
    size = os.path.getsize(path)
    append = offset is not None and 0 <= offset <= size
    start = offset if append else max(0, size - RUN_LOG_VIEW_MAX_BYTES)
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read()
    text, consumed = _decode_log_bytes(data, aligned=append or start == 0)
    return {
        "text": text,
        "append": append,
        "offset": start + consumed,
        "size": size,
        # Only a replacement read can drop the head of the log; on an append
        # `start` is just where the client left off, nothing was omitted.
        "skipped": 0 if append else start,
    }


def _run_log_markdown():
    """Render the complete run log as a Markdown document for download."""
    status = _run_status()
    path = status["log_path"] or RUN_LOG_PATH
    text = ""
    if os.path.exists(path):
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", errors="replace")
    if status["running"]:
        process_state = "running"
    elif status["returncode"] is not None:
        process_state = f"exited with code {status['returncode']}"
    else:
        process_state = "not started"
    # A log can legitimately contain backticks, so the fence has to outrun the
    # longest run of them in the body.
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    lines = [
        "# GAWorld Run Log",
        "",
        f"- Exported at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Log file: `{os.path.relpath(path, REPO_ROOT)}`",
        f"- Started at: {status['started_at'] or '-'}",
        f"- Process state: {process_state}",
        f"- Size: {status['log_size']} bytes",
        "",
        "## Output",
        "",
        fence + "text",
        text.rstrip("\n") if text.strip() else "(empty)",
        fence,
        "",
    ]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return "\n".join(lines), f"gaworld-run-log-{stamp}.md"


#: Shock-log entry types written by the employment life events.
_EMPLOYMENT_RECORD_TYPES = ("job_change", "unemployment", "rehired")


def _employment_payload(agent_id):
    """Current job + the job changes behind it, for the agent panel.

    Read from the per-agent economy state file — the only runtime artefact
    carrying a *live* job (the profile markdown holds the Day-1 one, which is
    exactly what stops being true after a 换工作/失业 event fires).
    """
    from gaworld.economy.finance import UNEMPLOYED_JOB_TEXT

    econ = _read_json_file(_memory_file(agent_id, "_economy"), {})
    if not isinstance(econ, dict) or not econ:
        return {}
    job = str(econ.get("job") or "")
    history = [row for row in econ.get("shock_log", [])
               if isinstance(row, dict) and row.get("type") in _EMPLOYMENT_RECORD_TYPES]
    return {
        "job": job,
        "status": "unemployed" if job == UNEMPLOYED_JOB_TEXT else "employed",
        "hourly_income": _num(econ.get("base_hourly_income"), 0.0),
        "previous_job": str(econ.get("previous_job") or ""),
        "recovery_days": int(_num(econ.get("_layoff_days_remaining"), 0)),
        "history": history[-5:],
    }


def _memory_payload(agent_id):
    memory_dir = _effective_config().get("memory_dir", "output/memory")
    base = os.path.join(REPO_ROOT, memory_dir)
    memory = _read_json_file(os.path.join(base, f"agent_{agent_id}.json"), [])
    schedule = _read_json_file(os.path.join(base, f"agent_{agent_id}_schedule.json"), {})
    habits = _read_json_file(os.path.join(base, f"agent_{agent_id}_habits.json"), {})
    intentions = _read_json_file(os.path.join(base, f"agent_{agent_id}_intentions.json"), {})
    goals = _read_json_file(os.path.join(base, f"agent_{agent_id}_goals.json"), {})
    episodes = _tail_text(os.path.join(base, f"agent_{agent_id}_episodes.jsonl"), max_chars=24000)
    log_text = _tail_text(os.path.join(REPO_ROOT, "output", "logs", f"agent_{agent_id}.log"), max_chars=24000)
    return {
        "memory": memory,
        "schedule": schedule,
        "habits": habits,
        "intentions": intentions,
        "goals": goals,
        "episodes_tail": episodes,
        "log_tail": log_text,
        "employment": _employment_payload(agent_id),
    }


def _agent_goals_payload(agent_id):
    memory_dir = _effective_config().get("memory_dir", "output/memory")
    base = os.path.join(REPO_ROOT, memory_dir)
    return _read_json_file(os.path.join(base, f"agent_{int(agent_id)}_goals.json"), {})


def _save_agent_goals_payload(agent_id, payload):
    from gaworld.goals import normalize_goals

    if not isinstance(payload, dict):
        raise ValueError("goals payload must be a JSON object")
    normalized = normalize_goals(payload, day=int(payload.get("last_review_day", 0) or 0))
    if not normalized:
        raise ValueError("goals payload has no valid goals")
    memory_dir = _effective_config().get("memory_dir", "output/memory")
    base = os.path.join(REPO_ROOT, memory_dir)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"agent_{int(agent_id)}_goals.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    return normalized
    return normalized


def _run_status(log_offset=None):
    proc = RUN_STATE.get("process")
    running = bool(proc and proc.poll() is None)
    code = None if not proc else proc.poll()
    log_path = RUN_STATE.get("log_path") or RUN_LOG_PATH
    chunk = _run_log_slice(log_path, log_offset)
    schedule = RUN_STATE.get("schedule") or {}
    return {
        "running": running,
        "returncode": code,
        "started_at": RUN_STATE.get("started_at"),
        "log_path": RUN_STATE.get("log_path"),
        # Only a schedule that still holds a live timer is pending; one whose
        # timer already fired lingers only to carry `schedule_error`.
        "scheduled_at": schedule.get("at") if schedule.get("timer") else None,
        "schedule_error": schedule.get("error"),
        # `log_append` tells the client whether to append `log_tail` to what it
        # already shows or replace it. Clients that send no offset always get a
        # replacement, so the field stays backwards compatible.
        "log_tail": chunk["text"],
        "log_append": chunk["append"],
        "log_offset": chunk["offset"],
        "log_size": chunk["size"],
        "log_skipped_bytes": chunk["skipped"],
    }


def _check_agent_ids_against_city():
    """Fail fast when the configured agent_ids do not exist in the chosen city.

    ``agent_ids`` is per-city, so switching to a smaller city leaves ids that
    point at nobody. ``build_agent`` resolves them with ``.iloc[0]`` on an empty
    match, which surfaces minutes later as a bare pandas IndexError in the run
    log — long after the operator has stopped watching. Checking here turns that
    into a sentence they can act on.
    """
    config = _effective_config()
    ref = str(config.get("city") or "").strip()
    if not ref:
        return
    wanted = _coerce_int_list(config.get("agent_ids", []))
    if not wanted:
        return
    try:
        from gaworld.city.bundle import resolve_city

        bundle = resolve_city(ref)
    except Exception:
        return  # a broken bundle is apply_city's problem, not this check's
    available = bundle.population_count
    if available <= 0:
        raise ValueError(
            f"城市「{bundle.display_name}」还没有居民，无法运行。"
            f"先到「城市」页签生成居民，或用 python -m gaworld.city add-agents {bundle.slug} --size 200"
        )
    missing = [item for item in wanted if item > available]
    if missing:
        raise ValueError(
            f"城市「{bundle.display_name}」只有 {available} 位居民，"
            f"但 Agent IDs 里有 {missing}。请改成 1–{available} 之间的编号。"
        )


def _coerce_int_list(values):
    out = []
    for item in values or []:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _start_simulation(payload):
    proc = RUN_STATE.get("process")
    if proc and proc.poll() is None:
        raise RuntimeError("Simulation is already running")
    if isinstance(payload.get("config"), dict):
        _save_config_patch(payload["config"])
    _check_agent_ids_against_city()
    os.makedirs(os.path.dirname(RUN_LOG_PATH), exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if payload.get("reset"):
        with open(RUN_LOG_PATH, "w", encoding="utf-8") as log_file:
            log_file.write(f"[dashboard] reset at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            reset = subprocess.run(
                [sys.executable, os.path.join(REPO_ROOT, "generative_city_sim.py"), "reset"],
                cwd=REPO_ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if reset.returncode != 0:
                raise RuntimeError("Reset failed; check dashboard run log")
    log_mode = "a" if payload.get("reset") else "w"
    log_file = open(RUN_LOG_PATH, log_mode, encoding="utf-8")
    log_file.write(f"\n[dashboard] run at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.flush()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO_ROOT, "generative_city_sim.py"), "run"],
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    RUN_STATE["process"] = proc
    RUN_STATE["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RUN_STATE["log_path"] = RUN_LOG_PATH
    return _run_status()


def _parse_schedule_time(raw):
    """Parse the ``datetime-local`` value the dashboard sends ("2026-08-30T21:30").

    Naive local time on purpose: the timer fires against the server's own clock,
    and the dashboard is a local console — browser and server share a machine.
    A value that does carry an offset is converted to local time first.
    """
    text = str(raw or "").strip().replace(" ", "T")
    if not text:
        raise ValueError("Scheduled time is required")
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Invalid scheduled time: {raw}")
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when


def _schedule_simulation(payload):
    """Arm a timer that starts the simulation at the requested wall clock.

    The config from the form is kept with the schedule and applied when the
    timer fires, so a scheduled run behaves exactly like pressing 运行仿真 then.
    """
    when = _parse_schedule_time(payload.get("at"))
    delay = (when - datetime.datetime.now()).total_seconds()
    if delay <= 0:
        raise ValueError("Scheduled time must be in the future")
    start_payload = {
        "reset": bool(payload.get("reset")),
        "config": payload.get("config"),
    }
    with _SCHEDULE_LOCK:
        previous = RUN_STATE.get("schedule") or {}
        if previous.get("timer"):
            previous["timer"].cancel()
        timer = threading.Timer(delay, _fire_scheduled_simulation)
        timer.daemon = True
        RUN_STATE["schedule"] = {
            "at": when.strftime("%Y-%m-%d %H:%M:%S"),
            "timer": timer,
            "payload": start_payload,
            "error": None,
        }
        timer.start()
    return _run_status()


def _cancel_scheduled_simulation():
    with _SCHEDULE_LOCK:
        schedule = RUN_STATE.get("schedule") or {}
        if schedule.get("timer"):
            schedule["timer"].cancel()
        RUN_STATE["schedule"] = None
    return _run_status()


def _fire_scheduled_simulation():
    with _SCHEDULE_LOCK:
        schedule = RUN_STATE.get("schedule")
        if not schedule:
            return
        # Drop the timer first: from here on the schedule is spent, and the
        # entry only survives long enough to report a failed start.
        schedule["timer"] = None
        start_payload = schedule.get("payload") or {}
    try:
        _start_simulation(start_payload)
    except Exception as exc:
        # Nobody is waiting on this call, so a failure has to be parked where
        # /api/run/status can show it instead of raising into the timer thread.
        _LOG.exception("Scheduled run failed to start: %s", exc)
        with _SCHEDULE_LOCK:
            schedule = RUN_STATE.get("schedule")
            if schedule:
                schedule["error"] = str(exc)
    else:
        with _SCHEDULE_LOCK:
            RUN_STATE["schedule"] = None


def _stop_simulation():
    proc = RUN_STATE.get("process")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    return _run_status()


def _interview_agent(payload):
    agent_id = int(payload.get("agent_id"))
    questions = payload.get("questions") or []
    if isinstance(questions, str):
        questions = [questions]
    questions = [str(item).strip() for item in questions if str(item).strip()]
    if not questions:
        raise ValueError("At least one question is required")
    command = [sys.executable, os.path.join(REPO_ROOT, "generative_city_sim.py"), "interview", "--agent-id", str(agent_id)]
    for question in questions:
        command.extend(["--question", question])
    if payload.get("context"):
        command.extend(["--context", str(payload["context"])])
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=int(payload.get("timeout", 300)),
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _latest_trace_meta():
    trace_path = os.path.join(REPO_ROOT, "output", "visualization", "simulation_trace.json")
    latest_path = os.path.join(REPO_ROOT, "output", "visualization", "latest_frame.json")
    trace = _read_json_file(trace_path, {})
    latest = _read_json_file(latest_path, {})
    return {
        "trace_meta": trace.get("meta", {}) if isinstance(trace, dict) else {},
        "latest": latest,
    }


def _replay_runs():
    """Every replayable trace on disk: the live run, archives, scenario runs."""
    visualization_dir = _effective_config().get("visualization", {}).get("output_dir", "output/visualization")
    return replay_runs.list_runs(REPO_ROOT, visualization_dir)


def _current_trace_frame():
    latest = _latest_trace_meta().get("latest", {})
    if isinstance(latest, dict) and isinstance(latest.get("frame"), dict):
        return latest["frame"]
    return {}


def _life_events_payload():
    return {
        "templates": list_life_event_templates(),
        "events": list_life_events(CONFIG, include_consumed=True),
    }


def _add_life_event(payload):
    event = add_life_event(
        _expand_candidate_payload(payload), CONFIG, current_frame=_current_trace_frame()
    )
    return {
        "event": event,
        "events": list_life_events(CONFIG, include_consumed=True),
    }


# ---------------------------------------------------------------------------
# State-aware life-event candidates. `gaworld.events.candidates` ranks a
# catalogue against one agent's situation; the reading of that situation off
# the files on disk is this module's job (see `context_from_agent`).
# ---------------------------------------------------------------------------

def _expand_candidate_payload(payload):
    """Turn a tag-cloud click into a full life-event body.

    A ``candidate_key`` is the cloud's shorthand: the catalogue already holds
    that event's title, description, severity and effects, so the client sends
    the key and the agent rather than restating all of it. A payload from the
    事件模板 form carries no key and passes through untouched.
    """
    candidate_key = str(payload.get("candidate_key") or "").strip()
    if not candidate_key:
        return payload
    return candidate_events.candidate_event_payload(
        candidate_key,
        agent_ids=payload.get("agent_ids", ()),
        severity=payload.get("severity"),
    )


def _agent_job(agent_id):
    """The 职业与工作节奏 line from the Markdown profile.

    The state CSV has no job column — the job is prose, and the candidate
    gates read it (平台规则突变 for platform workers, 创业失败 for the
    self-employed). Same field `agents_loader.parse_profile` pulls, without
    that parser's hard requirement on the other profile fields.
    """
    profile = _agent_profile(agent_id) or {}
    match = re.search(r"\*\*职业与工作节奏\*\*：(.+)", profile.get("text", ""))
    return match.group(1).strip() if match else ""


def _agent_family_record(agent_id):
    """This agent's recorded household, or None before the first run."""
    from gaworld.apps import family_api

    agent_id = int(agent_id)
    for row in family_api.overview().get("agents", []):
        try:
            if int(row.get("agent_id")) == agent_id:
                return row
        except (TypeError, ValueError):
            continue
    return None


def _life_event_history(agent_id):
    """This agent's life events in the shape `cooldown_keys` reads.

    A pending event carries no day — it has not fired, and `cooldown_keys`
    hides its tag on that basis alone rather than putting it on a clock.
    """
    from gaworld.events.life import life_events_for_agent

    events = list_life_events(CONFIG, include_consumed=True)
    return [
        {
            "key": event.get("template_key"),
            "day": event.get("triggered_day", event.get("day")),
            "pending": event.get("status", "pending") == "pending",
        }
        for event in life_events_for_agent(events, agent_id)
    ]


def _life_event_current_day(history):
    """The simulation day the cooldowns are measured against.

    A live run publishes the day in its latest frame. Between runs there is no
    frame, and falling back to 0 would make every past event look like it
    fired in the future — which `cooldown_keys` reads as a reset run and
    stops hiding anything. The last day something fired is the honest floor.
    """
    day = _current_trace_frame().get("day")
    if day is not None:
        return day
    fired = [
        item["day"]
        for item in history or []
        if isinstance(item, dict) and not item.get("pending") and item.get("day") is not None
    ]
    return max(fired, default=0)


def _life_event_candidate_context(agent_id):
    """The gate context for one agent, or None if there is no such agent."""
    state = _agent_state(agent_id)
    if state is None:
        return None
    record = _agent_family_record(agent_id)
    finance = _agent_finance(agent_id) or {}
    context = candidate_events.context_from_agent(
        {
            "id": state["id"],
            "name": state["name"],
            "age": state["age"],
            "hukou": state["hukou"],
            "job": _agent_job(agent_id),
            "state": state["state"],
            "family_facts": family_facts(record) if record else None,
            "economy": {
                "balance": finance.get("balance", 0.0),
                "debt": finance.get("debt", 0.0),
            },
        }
    )
    # Cooldowns are measured in simulation days, so they need the run's clock.
    history = _life_event_history(agent_id)
    context["day"] = _life_event_current_day(history)
    context["recent_events"] = history
    return context


def _life_event_candidates_payload(agent_id, limit=None):
    context = _life_event_candidate_context(agent_id)
    if context is None:
        return None
    return {
        "agent_id": int(agent_id),
        "agent_name": context.get("name", ""),
        # The client polls this endpoint and repaints only when the digest
        # moves, so a tag cloud that has not changed costs it no DOM work.
        "signature": candidate_events.context_signature(context),
        "candidates": candidate_events.rank_life_event_candidates(
            context,
            candidate_events.DEFAULT_CANDIDATE_LIMIT if limit is None else limit,
        ),
    }


def _resolve_output_dir(output_dir: str | None) -> str:
    """Resolve the output directory path.

    If ``output_dir`` is empty or None, default to the current run root under
    REPO_ROOT — ``output/``, or ``output/cities/<slug>/`` with a city selected.
    If it's a relative path, resolve it against REPO_ROOT.
    """
    if not output_dir:
        return os.path.join(REPO_ROOT, _effective_config().get("run_output_dir", "output"))
    p = Path(output_dir)
    if p.is_absolute():
        return str(p)
    return os.path.join(REPO_ROOT, output_dir)


def _agent_name_map():
    return {section["id"]: section["name"] for section in _profile_sections()[1]}


def _live_analytics_paths():
    """Where the current run writes the artifacts Analytics reads."""
    config = _effective_config()
    return {
        # Not a literal "output": a selected city moves the whole run tree to
        # `output/cities/<slug>/`, and Analytics reads `state/` and `economy/`
        # relative to this root.
        "output_dir": os.path.join(REPO_ROOT, config.get("run_output_dir", "output")),
        "memory_dir": os.path.join(REPO_ROOT, config.get("memory_dir", "output/memory")),
        "visualization_dir": os.path.join(
            REPO_ROOT, config.get("visualization", {}).get("output_dir", "output/visualization")
        ),
        "diary_dir": os.path.join(REPO_ROOT, config.get("diary_output_dir", "output/diaries")),
    }


def _analytics_run_paths(run_id, runs=None):
    """Resolve a replay run id to the artifact dirs Analytics reads, or None.

    Only ids that ``/api/replay/runs`` actually listed are accepted, which also
    keeps the query parameter from reaching outside the repo.
    """
    if not run_id:
        return _live_analytics_paths()
    run = next((item for item in (runs if runs is not None else _replay_runs()) if item["id"] == run_id), None)
    if run is None:
        return None
    if run["kind"] == "live":
        return _live_analytics_paths()

    config = _effective_config()
    visualization_dir = os.path.join(REPO_ROOT, run["id"])
    if run["kind"] == "archive":
        # An archived run keeps only its trace; its sibling artifacts belong to
        # whichever run overwrote them since, so they are deliberately not read
        # — the missing dirs below make those sections report "no data".
        base = visualization_dir
    else:
        base = os.path.dirname(visualization_dir)
    return {
        "output_dir": base,
        # A scenario run mirrors the live tree's layout inside its own output
        # dir, so the configured dir names apply, not their full paths.
        "memory_dir": os.path.join(base, os.path.basename(config.get("memory_dir", "memory"))),
        "visualization_dir": visualization_dir,
        "diary_dir": os.path.join(base, os.path.basename(config.get("diary_output_dir", "diaries"))),
    }


def _analytics_runs():
    """Replayable runs, each tagged with the Analytics sections it can fill.

    The dashboard uses the flags to explain up front why an archived run shows
    an event timeline but no state curves.
    """
    runs = _replay_runs()
    listed = []
    for run in runs:
        paths = _analytics_run_paths(run["id"], runs=runs)
        if paths is None:  # pragma: no cover - ids come from the same listing
            continue
        memory_dir = paths["memory_dir"]
        has_memory = os.path.isdir(memory_dir) and any(
            name.startswith("agent_") for name in os.listdir(memory_dir)
        )
        listed.append(
            {
                "id": run["id"],
                "kind": run["kind"],
                "label": run["label"],
                "frame_count": run["frame_count"],
                "finished": run["finished"],
                "generated_at": run["generated_at"],
                "last_updated": run["last_updated"],
                "sim_days": run["sim_days"],
                "agent_count": run["agent_count"],
                "sections": {
                    "state-history": os.path.exists(
                        os.path.join(paths["output_dir"], "state", "agent_state_history.csv")
                    ),
                    "economy": os.path.exists(
                        os.path.join(paths["output_dir"], "economy", "daily_ledger.csv")
                    ),
                    "social": has_memory,
                    "behavior": has_memory,
                    "events": os.path.exists(
                        os.path.join(paths["visualization_dir"], "simulation_trace.json")
                    ),
                },
            }
        )
    return listed


def _analytics_payload(section, paths=None):
    """Dispatch one Analytics section against a run's artifacts."""
    paths = paths or _live_analytics_paths()
    names = _agent_name_map()
    if section == "overview":
        return analytics.overview(
            paths["output_dir"],
            paths["memory_dir"],
            paths["visualization_dir"],
            paths["diary_dir"],
            names,
        )
    if section == "state-history":
        return analytics.state_history(paths["output_dir"], names)
    if section == "economy":
        return analytics.economy(paths["output_dir"], names)
    if section == "social":
        return analytics.social(paths["memory_dir"], names)
    if section == "behavior":
        return analytics.behavior(paths["memory_dir"], names)
    if section == "events":
        return analytics.events(paths["visualization_dir"])
    return None


def _fos_export(payload: dict) -> dict:
    """Handle ``POST /api/fos-export``.

    Reads simulation output from the provided (or default) output directory,
    calls GAWorld's LLM for analysis, and returns a FOS-ready prompt.
    """
    raw_dir = payload.get("output_dir") or ""
    hint = payload.get("hint") or None
    english = bool(payload.get("english", False))

    resolved = _resolve_output_dir(raw_dir)
    result = generate_fos_prompt(
        output_dir=Path(resolved),
        hint=hint,
        english=english,
    )
    return {
        "prompt": result.get("prompt"),
        "summary": result.get("summary"),
        "error": result.get("error"),
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "GAWorldDashboard/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    def end_headers(self):
        # The dashboard JS/CSS and trace JSON change between runs; without
        # this, browsers serve stale assets from memory cache indefinitely.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json_response(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _download_response(self, data, content_type, filename):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location, status=303):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _read_form_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _handle_api_get(self, path, query):
        # Population Studio / group mode live in their own module; this file is
        # already long enough without another subsystem's routes in it.
        if path.startswith("/api/population"):
            from gaworld.apps import population_api

            payload, status = population_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/family"):
            from gaworld.apps import family_api

            payload, status = family_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        # Trailing slash on purpose: the single-agent `POST /api/interview`
        # below is a different, older endpoint and must not be shadowed.
        if path.startswith("/api/interview/"):
            from gaworld.apps import interview_api

            payload, status = interview_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/persona/"):
            from gaworld.apps import persona_api

            payload, status = persona_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/external-systems"):
            from gaworld.apps import external_systems_api

            payload, status = external_systems_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/parallel-worlds"):
            from gaworld.apps import parallel_worlds_api

            payload, status = parallel_worlds_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/settings"):
            from gaworld.apps import settings_api

            payload, status = settings_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/city"):
            from gaworld.apps import city_api

            payload, status = city_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path == "/api/config":
            return self._json_response(_config_summary())
        if path == "/api/agents":
            return self._json_response({"agents": _agents_summary()})
        if path == "/api/skills":
            return self._json_response({"skills": _skills_library()})
        if path.startswith("/api/agents/") and path.endswith("/profile"):
            agent_id = path.split("/")[3]
            profile = _agent_profile(agent_id)
            if not profile:
                return self._json_response({"error": "Profile not found"}, status=404)
            return self._json_response(profile)
        if path.startswith("/api/agents/") and path.endswith("/state"):
            agent_id = path.split("/")[3]
            state = _agent_state(agent_id)
            if state is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            return self._json_response(state)
        if path.startswith("/api/agents/") and path.endswith("/big5"):
            agent_id = path.split("/")[3]
            data = _agent_big5(agent_id)
            if data is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            return self._json_response(data)
        if path.startswith("/api/agents/") and path.endswith("/detail"):
            agent_id = path.split("/")[3]
            detail = _agent_detail(agent_id)
            if detail is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            return self._json_response(detail)
        if path.startswith("/api/agents/") and path.endswith("/memory"):
            agent_id = path.split("/")[3]
            return self._json_response(_memory_payload(agent_id))
        if path.startswith("/api/agents/") and path.endswith("/goals"):
            agent_id = path.split("/")[3]
            return self._json_response(_agent_goals_payload(agent_id))
        if path.startswith("/api/analytics/"):
            section = path[len("/api/analytics/") :]
            if section == "runs":
                return self._json_response({"runs": _analytics_runs()})
            # No ?run= means the current run, so bookmarked links keep working.
            paths = _analytics_run_paths((query.get("run") or [""])[0])
            if paths is None:
                return self._json_response({"error": "Unknown run"}, status=404)
            payload = _analytics_payload(section, paths)
            if payload is None:
                return self._json_response({"error": "Unknown analytics section"}, status=404)
            return self._json_response(payload)
        if path == "/api/run/status":
            raw_offset = (query.get("log_offset") or [""])[0].strip()
            return self._json_response(_run_status(int(raw_offset) if raw_offset else None))
        if path == "/api/run/log/export":
            markdown, filename = _run_log_markdown()
            return self._download_response(
                markdown.encode("utf-8"), "text/markdown; charset=utf-8", filename
            )
        if path == "/api/trace/meta":
            return self._json_response(_latest_trace_meta())
        if path == "/api/replay/runs":
            return self._json_response({"runs": _replay_runs()})
        if path == "/api/life-events":
            return self._json_response(_life_events_payload())
        if path == "/api/life-events/candidates":
            agent_id = (query.get("agent_id") or [""])[0].strip()
            if not agent_id:
                return self._json_response({"error": "agent_id is required"}, status=400)
            raw_limit = (query.get("limit") or [""])[0].strip()
            payload = _life_event_candidates_payload(
                agent_id, int(raw_limit) if raw_limit else None
            )
            if payload is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            return self._json_response(payload)
        if path == "/api/todos":
            return self._json_response(_todo_board_payload())

        if path == "/api/collaboration/sessions":
            service = _get_collaboration_service()
            kind = (query.get("kind") or [""])[0]
            status = (query.get("status") or [""])[0]
            sessions = service.list_sessions(
                kind=kind,
                status=status,
            )
            return self._json_response(
                {
                    "sessions": [
                        _public_collaboration_session(item)
                        for item in sessions
                    ],
                    "health": service.health(),
                }
            )
        parts = path.strip("/").split("/")
        if (
            len(parts) == 4
            and parts[:3] == ["api", "collaboration", "sessions"]
        ):
            session = _get_collaboration_service().get_session(parts[3])
            return self._json_response(
                _public_collaboration_session(session)
            )
        if (
            len(parts) == 5
            and parts[:3] == ["api", "collaboration", "sessions"]
            and parts[4] == "events"
        ):
            after = int((query.get("after") or [0])[0])
            events = _get_collaboration_service().events(
                parts[3],
                after=after,
            )
            return self._json_response({"events": events})
        return self._json_response({"error": "Unknown endpoint"}, status=404)

    def _handle_api_post(self, path):
        payload = self._read_json_body()
        if path.startswith("/api/population"):
            from gaworld.apps import population_api

            body, status = population_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path.startswith("/api/family"):
            from gaworld.apps import family_api

            body, status = family_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        # Trailing slash: `/api/interview` alone stays the single-agent
        # endpoint handled further down.
        if path.startswith("/api/interview/"):
            from gaworld.apps import interview_api

            body, status = interview_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path.startswith("/api/persona/"):
            from gaworld.apps import persona_api

            body, status = persona_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path.startswith("/api/external-systems"):
            from gaworld.apps import external_systems_api

            body, status = external_systems_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path.startswith("/api/parallel-worlds"):
            from gaworld.apps import parallel_worlds_api

            body, status = parallel_worlds_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path.startswith("/api/settings"):
            from gaworld.apps import settings_api

            body, status = settings_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path.startswith("/api/city"):
            from gaworld.apps import city_api

            body, status = city_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path == "/api/config":
            return self._json_response(_save_config_patch(payload))
        if path == "/api/agents":
            return self._json_response(_create_agent(payload))
        if path.startswith("/api/agents/") and path.endswith("/profile"):
            agent_id = path.split("/")[3]
            return self._json_response(_save_agent_profile(agent_id, payload.get("text", "")))
        if path.startswith("/api/agents/") and path.endswith("/state"):
            agent_id = path.split("/")[3]
            return self._json_response(_save_agent_state(agent_id, payload))
        if path.startswith("/api/agents/") and path.endswith("/big5"):
            agent_id = path.split("/")[3]
            try:
                return self._json_response(_save_agent_big5(agent_id, payload))
            except ValueError as exc:
                return self._json_response({"error": str(exc)}, status=400)
        if path.startswith("/api/agents/") and path.endswith("/goals"):
            agent_id = path.split("/")[3]
            try:
                saved = _save_agent_goals_payload(agent_id, payload)
            except ValueError as exc:
                return self._json_response({"error": str(exc)}, status=400)
            return self._json_response(saved)
        if path.startswith("/api/agents/") and path.endswith("/memory"):
            agent_id = path.split("/")[3]
            return self._json_response(_append_agent_memory(agent_id, payload))
        if path.startswith("/api/agents/") and path.endswith("/relationships"):
            agent_id = path.split("/")[3]
            return self._json_response(_save_agent_relationships(agent_id, payload))
        if path.startswith("/api/agents/") and path.endswith("/finance"):
            agent_id = path.split("/")[3]
            return self._json_response(_save_agent_finance(agent_id, payload))
        if path == "/api/run/start":
            return self._json_response(_start_simulation(payload))
        if path == "/api/run/stop":
            return self._json_response(_stop_simulation())
        if path == "/api/run/schedule":
            return self._json_response(_schedule_simulation(payload))
        if path == "/api/run/schedule/cancel":
            return self._json_response(_cancel_scheduled_simulation())
        if path == "/api/interview":
            return self._json_response(_interview_agent(payload))
        if path == "/api/life-events":
            return self._json_response(_add_life_event(payload))
        if path == "/api/todos":
            return self._json_response(_save_todo_board(payload.get("items", [])))
        if path == "/api/todos/create":
            return self._json_response(_create_todo_item(payload))
        if path == "/api/todos/update":
            return self._json_response(_update_todo_item(payload))
        if path == "/api/todos/clear":
            return self._json_response(_save_todo_board([]))
        if path == "/api/fos-export":
            return self._json_response(_fos_export(payload))
        if path == "/api/relationships/friends":
            return self._json_response(
                _get_collaboration_service().make_friends(
                    _collaboration_agent_ids(payload)
                )
            )
        if path == "/api/collaboration/sessions":
            service = _get_collaboration_service()
            kind = _collaboration_text(payload, "kind")
            agent_ids = _collaboration_agent_ids(payload)
            if kind == "discussion":
                session = service.create_discussion(
                    agent_ids,
                    topic=_collaboration_text(payload, "topic"),
                    max_rounds=_collaboration_integer(
                        payload,
                        "max_rounds",
                        default=6,
                    ),
                )
            elif kind == "cooperation":
                session = service.create_cooperation(
                    agent_ids,
                    task=_collaboration_text(payload, "task"),
                    leader_id=_collaboration_integer(
                        payload,
                        "leader_id",
                        allow_none=True,
                    ),
                    role_overrides=_collaboration_roles(payload),
                )
            else:
                raise ValueError(
                    "kind must be discussion or cooperation"
                )
            return self._json_response(
                _public_collaboration_session(session.to_dict())
            )
        parts = path.strip("/").split("/")
        if (
            len(parts) == 5
            and parts[:3] == ["api", "collaboration", "sessions"]
            and parts[4] in {"pause", "resume", "cancel"}
        ):
            service = _get_collaboration_service()
            result = getattr(service, parts[4])(parts[3])
            return self._json_response(
                _public_collaboration_session(result)
            )
        return self._json_response({"error": "Unknown endpoint"}, status=404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            try:
                return self._handle_api_get(path, parse_qs(parsed.query))
            except (ValueError, KeyError) as exc:
                return self._json_response(
                    {"error": str(exc)},
                    status=400,
                )
            except Exception as exc:
                # HTTP boundary: log the full traceback and surface a 500.
                _LOG.exception("GET %s failed: %s", path, exc)
                return self._json_response({"error": str(exc)}, status=500)
        # "/" is the project landing page — the intro and the way in to every
        # console view. The console itself keeps the /console route it already
        # had, so nothing that linked to it breaks. To go back to opening the
        # console at the root, point "/" at /site/console/index.html again.
        if path in ("/", ""):
            self.path = "/site/index.html"
        elif path in ("/console", "/console/"):
            self.path = "/site/console/index.html"
        elif path in ("/dashboard", "/dashboard/"):
            self.path = "/site/dashboard/index.html"
        elif path in ("/board", "/board/", "/todo", "/todo/"):
            self.path = "/docs/todo_board.html"
        return super().do_GET()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        # "/" is the project landing page — the intro and the way in to every
        # console view. The console itself keeps the /console route it already
        # had, so nothing that linked to it breaks. To go back to opening the
        # console at the root, point "/" at /site/console/index.html again.
        if path in ("/", ""):
            self.path = "/site/index.html"
        elif path in ("/console", "/console/"):
            self.path = "/site/console/index.html"
        elif path in ("/dashboard", "/dashboard/"):
            self.path = "/site/dashboard/index.html"
        elif path in ("/board", "/board/", "/todo", "/todo/"):
            self.path = "/docs/todo_board.html"
        return super().do_HEAD()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/todos/create-form":
            try:
                _create_todo_item(self._read_form_body())
                return self._redirect("/board")
            except (ValueError, KeyError) as exc:
                return self._json_response({"error": str(exc)}, status=400)
            except Exception as exc:
                _LOG.exception("POST %s failed: %s", path, exc)
                return self._json_response({"error": str(exc)}, status=500)
        if not path.startswith("/api/"):
            return self._json_response({"error": "POST is only supported under /api"}, status=404)
        try:
            return self._handle_api_post(path)
        except (ValueError, KeyError) as exc:
            return self._json_response(
                {"error": str(exc)},
                status=400,
            )
        except Exception as exc:
            # HTTP boundary: log the full traceback and surface a 500.
            _LOG.exception("POST %s failed: %s", path, exc)
            return self._json_response({"error": str(exc)}, status=500)


def run_server(host="127.0.0.1", port=8766):
    server = ThreadingHTTPServer((host, int(port)), DashboardHandler)
    url = f"http://{host}:{int(port)}/"
    print(f"GAWorld console: {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_simulation()
        _reset_collaboration_service_for_tests()
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Serve the GAWorld local dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
