import atexit
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import types
import uuid
from copy import deepcopy
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld import accounts, worlds
from gaworld.accounts import context as request_context
from gaworld.accounts import policy as access_policy
from gaworld.apps import accounts_api, analytics, replay_runs, residents, routes, runs
from gaworld.apps import world_paths as paths
from gaworld.events import candidates as candidate_events
from gaworld.events.life import add_life_event, list_life_event_templates, list_life_events
from gaworld.family.lifecycle import family_facts
from gaworld.integrations.fos_prompt import generate_fos_prompt
from gaworld.io.avatar import build_agent_avatar_svg
from gaworld.logging_setup import get_logger
from gaworld.settings import CONFIG

_LOG = get_logger("gaworld.dashboard")


DASHBOARD_ROOT = os.path.join(paths.REPO_ROOT, "site", "dashboard")
TODO_BOARD_PATH = os.path.join(paths.REPO_ROOT, "output", "dashboard", "todo_board.json")



TODO_LOCK = threading.RLock()

_COLLABORATION_SERVICE = None
_COLLABORATION_LOCK = threading.Lock()

#: The request's active world (a row from the account database), or None for
#: the shared default world. Set by ``_guard`` per request; every path helper
#: below reads it, so the module constants above stay the default world's.
_WORLD = request_context.WORLD
#: The signed-in user of the request (None in single-user mode). Queued and
#: scheduled starts carry it in their copied context, for the per-user limit.
_USER = request_context.USER
WORLD_COOKIE = "gaworld_world"


























def _todo_board_payload():
    with TODO_LOCK:
        payload = paths.read_json_file(TODO_BOARD_PATH, {"items": []})
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
        paths.atomic_write_json(TODO_BOARD_PATH, payload)
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






def _city_source_config(city):
    """``(slug, config)`` of the population a new world is copied from."""
    from gaworld.city.config import apply_city
    from gaworld.settings.defaults import build_default_config

    cfg = build_default_config()
    slug = ""
    if city:
        from gaworld.city.bundle import CityNotFoundError, resolve_city

        try:
            bundle = resolve_city(city)
        except CityNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        if bundle.population_count <= 0:
            raise ValueError(f"城市「{bundle.display_name}」还没有居民，无法建立世界")
        slug = bundle.slug
        cfg["city"] = slug
        apply_city(cfg, root=paths.REPO_ROOT)
    return slug, cfg


def _city_seed_files(city):
    """``(slug, state_csv, profiles_md)`` a new world copies its residents from.

    ``city`` empty means the default population under ``data/``.
    """
    slug, cfg = _city_source_config(city)
    csv_src = os.path.join(paths.REPO_ROOT, str(cfg.get("csv_path") or ""))
    md_src = os.path.join(paths.REPO_ROOT, str(cfg.get("md_path") or ""))
    if not (os.path.isfile(csv_src) and os.path.isfile(md_src)):
        raise ValueError("找不到这座城市的居民文件")
    return slug, csv_src, md_src


def _city_agent_files(city):
    """``{config path: file}`` of the agent-keyed inputs a new world copies
    from its city (``worlds.COPIED_AGENT_FILES``) — only those that exist."""
    _slug, cfg = _city_source_config(city)
    found = {}
    for path in worlds.COPIED_AGENT_FILES:
        node = cfg
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, str) and node:
            source = node if os.path.isabs(node) else os.path.join(paths.REPO_ROOT, node)
            if os.path.isfile(source):
                found[path] = source
    return found


def _repo_path(value):
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    return (Path(paths.REPO_ROOT) / path).resolve()


def _collaboration_config():
    config = paths.effective_config().get("collaboration", {})
    return config if isinstance(config, dict) else {}


def _get_collaboration_service():
    global _COLLABORATION_SERVICE
    with _COLLABORATION_LOCK:
        if _COLLABORATION_SERVICE is not None:
            return _COLLABORATION_SERVICE

        from gaworld.collaboration.service import CollaborationService
        from gaworld.llm.providers import call_llm
        from gaworld.memory.experience import append_agent_episode

        config = paths.effective_config()
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
            agent_loader=lambda agent_id: residents.agent_detail(int(agent_id)),
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

    repo_root = Path(paths.REPO_ROOT).resolve()
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
    cfg = paths.effective_config()
    world = paths.current_world()
    # The layer the run toolbar edits: the world's own config, or the global file.
    layer = worlds.read_config(paths.REPO_ROOT, world["id"]) if world else paths.dashboard_config()
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
        "multiplayer": cfg.get("multiplayer", {}),
        "cluster": {"sync_timeout_seconds": (cfg.get("cluster") or {}).get("sync_timeout_seconds", 60)},
        "dashboard_config": layer,
        "city": layer.get("city", ""),
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
                unit, count, start_date=_sim_start_date(paths.effective_config())
            )
    if "agent_ids" in payload:
        ids = payload.get("agent_ids")
        if isinstance(ids, str):
            # Accept "12" as "agents 1..12" — a single integer is shorthand
            # for "first N residents" — and "1,2,3" as a literal list. The
            # field hint in the UI already promises this; the parser now
            # actually does it.
            stripped = ids.strip()
            if stripped and "," not in stripped and stripped.isdigit():
                ids = list(range(1, int(stripped) + 1))
            else:
                ids = [part.strip() for part in stripped.split(",")]
        # Drop tokens that aren't integers — a typo in the field shouldn't
        # 400 the whole config save.
        patch["agent_ids"] = []
        for item in ids or []:
            text = str(item).strip()
            if not text:
                continue
            try:
                patch["agent_ids"].append(int(text))
            except (TypeError, ValueError):
                continue
    if "simulate_realtime" in payload:
        patch["simulate_realtime"] = bool(payload["simulate_realtime"])
    multiplayer = payload.get("multiplayer")
    if isinstance(multiplayer, dict) and "wait_for_players_seconds" in multiplayer:
        # Each tick waits up to this long for the people playing residents.
        seconds = max(0, min(300, int(multiplayer["wait_for_players_seconds"] or 0)))
        patch["multiplayer"] = {"wait_for_players_seconds": seconds}
    cluster = payload.get("cluster")
    if isinstance(cluster, dict) and "sync_timeout_seconds" in cluster:
        # A distributed world's tick waits up to this long for its slowest machine.
        seconds = max(0, min(600, int(cluster["sync_timeout_seconds"] or 0)))
        patch["cluster"] = {"sync_timeout_seconds": seconds}
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
    world = paths.current_world()
    current = worlds.read_config(paths.REPO_ROOT, world["id"]) if world else paths.dashboard_config()
    patch = _sanitize_config_patch(payload)
    if world:
        # A world's residents were copied from its city when it was made;
        # pointing it at another city would mix two populations.
        patch.pop("city", None)
    paths.deep_update(current, patch)
    paths.atomic_write_json(paths.config_path(), current)
    if "multiplayer" in patch:
        # The multiplayer plugin reads this every tick: hand it to a running
        # simulator now rather than at its next start.
        from gaworld.apps import kernel_api
        from gaworld.kernel import remote

        try:
            remote.enqueue(
                kernel_api._queue_path(),
                "update_config",
                {"path": "multiplayer.wait_for_players_seconds", "value": patch["multiplayer"]["wait_for_players_seconds"]},
            )
        except LookupError:
            pass  # nothing running; the next run reads the saved config
    if "cluster" in patch:
        # Every simulator of the world reads it each tick; the nodes' runs pick
        # it up at their next start.
        from gaworld.apps import kernel_api
        from gaworld.kernel import remote

        try:
            remote.enqueue(
                kernel_api._queue_path(),
                "update_config",
                {"path": "cluster.sync_timeout_seconds", "value": patch["cluster"]["sync_timeout_seconds"]},
            )
        except LookupError:
            pass
        if world:
            from gaworld.apps import cluster_api

            cluster_api.broadcast(
                world["id"],
                "update_config",
                {"path": "cluster.sync_timeout_seconds", "value": patch["cluster"]["sync_timeout_seconds"]},
            )
    return _config_summary()










# ---------------------------------------------------------------------------
# Agent state (CSV seed) read / write, skills, finance, and agent creation.
# The CSV is the machine-readable seed the simulator loads; the Markdown
# profile is the narrative twin. Studio edits go to the CSV for state vars and
# to the profile block for narrative, mirroring how imported agents are stored.
# ---------------------------------------------------------------------------








































# --- Memory content (Studio step 4) -----------------------------------------
# The counts alone don't say what an agent actually remembers, so the Studio
# also reads the memory bodies. Lists are capped to keep the detail payload —
# which the collaboration service reuses per LLM turn — from ballooning.















# --- Finance (Studio step 7) ------------------------------------------------
# The per-agent economy JSON is the simulator's live state and is reloaded on
# the next stateful run, so that is what the Studio edits. The wealth snapshot
# CSV is a run artifact — readable, but not a place to write back into.

















# ---------------------------------------------------------------------------
# Big Five (OCEAN) seed scores — studio panel, step 2.
# ---------------------------------------------------------------------------






































def _run_log_markdown():
    """Render the complete run log as a Markdown document for download."""
    status = runs.run_status()
    path = status["log_path"] or paths.run_log_path()
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
        f"- Log file: `{os.path.relpath(path, paths.REPO_ROOT)}`",
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


































































def _interview_agent(payload):
    agent_id = int(payload.get("agent_id"))
    questions = payload.get("questions") or []
    if isinstance(questions, str):
        questions = [questions]
    questions = [str(item).strip() for item in questions if str(item).strip()]
    if not questions:
        raise ValueError("At least one question is required")
    script = os.path.join(paths.REPO_ROOT, "generative_city_sim.py")
    command = [sys.executable, script, "interview", "--agent-id", str(agent_id)]
    for question in questions:
        command.extend(["--question", question])
    if payload.get("context"):
        command.extend(["--context", str(payload["context"])])
    result = subprocess.run(
        command,
        cwd=paths.REPO_ROOT,
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


def _trace_payload():
    output_dir = paths.effective_config().get("visualization", {}).get("output_dir", "output/visualization")
    trace_path = os.path.join(paths.REPO_ROOT, output_dir, "simulation_trace.json")
    latest_path = os.path.join(paths.REPO_ROOT, output_dir, "latest_frame.json")
    trace = paths.read_json_file(trace_path, {})
    latest = paths.read_json_file(latest_path, {})
    return {
        "trace": trace if isinstance(trace, dict) else {},
        "latest": latest if isinstance(latest, dict) else {},
    }


def _latest_trace_meta():
    payload = _trace_payload()
    return {
        "trace_meta": payload["trace"].get("meta", {}),
        "latest": payload["latest"],
    }


def _replay_runs():
    """Every replayable trace on disk: the live run, archives, scenario runs."""
    visualization = paths.effective_config().get("visualization", {})
    visualization_dir = visualization.get("output_dir", "output/visualization")
    runs = replay_runs.list_runs(paths.REPO_ROOT, visualization_dir)
    store = accounts.enabled_store(paths.REPO_ROOT)
    if store is None:
        return runs
    # The scan finds every world's traces; list only the worlds this user may see.
    seen = {}

    def visible(run):
        parts = run["id"].split("/")
        if parts[:2] != ["output", "worlds"] or len(parts) < 3:
            return True
        if parts[2] not in seen:
            world = store.get_world(parts[2])
            seen[parts[2]] = bool(world and world_readable(world, _USER.get()))
        return seen[parts[2]]

    return [run for run in runs if visible(run)]


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
    profile = residents.agent_profile(agent_id) or {}
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
    state = residents.agent_state(agent_id)
    if state is None:
        return None
    record = _agent_family_record(agent_id)
    finance = residents.agent_finance(agent_id) or {}
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
        return os.path.join(paths.REPO_ROOT, paths.effective_config().get("run_output_dir", "output"))
    p = Path(output_dir)
    if p.is_absolute():
        return str(p)
    return os.path.join(paths.REPO_ROOT, output_dir)


def _agent_name_map():
    return {section["id"]: section["name"] for section in residents.profile_sections()[1]}


def _live_analytics_paths():
    """Where the current run writes the artifacts Analytics reads."""
    config = paths.effective_config()
    return {
        # Not a literal "output": a selected city moves the whole run tree to
        # `output/cities/<slug>/`, and Analytics reads `state/` and `economy/`
        # relative to this root.
        "output_dir": os.path.join(paths.REPO_ROOT, config.get("run_output_dir", "output")),
        "memory_dir": os.path.join(paths.REPO_ROOT, config.get("memory_dir", "output/memory")),
        "visualization_dir": os.path.join(
            paths.REPO_ROOT, config.get("visualization", {}).get("output_dir", "output/visualization")
        ),
        "diary_dir": os.path.join(paths.REPO_ROOT, config.get("diary_output_dir", "output/diaries")),
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

    config = paths.effective_config()
    visualization_dir = os.path.join(paths.REPO_ROOT, run["id"])
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


#: Page routes rewritten onto a file under /site or /docs in do_GET / do_HEAD.
STATIC_ROUTES = frozenset(
    ("/", "", "/console", "/console/", "/dashboard", "/dashboard/", "/board", "/board/", "/todo", "/todo/")
) | frozenset(access_policy.PUBLIC_PAGES)

DENIALS = {
    "admin": "没有权限：该操作需要管理员",
    "city": "没有权限：需要「建立城市」权限",
    "world": "没有权限：只有世界的创建者能修改它（共享的默认世界只限管理员）",
}


def world_readable(world, user):
    """Owners and admins see a world; others only once it is shared."""
    if user is None:
        return False
    return user.get("role") == "admin" or world.get("owner_id") == user.get("id") or world.get("visibility") != "private"


#: user id -> wall time of their latest request; the teacher console's
#: "online" dot. In memory only: a restart forgets, which is fine for a dot.
LAST_SEEN = {}


#: Who a request carrying GAWORLD_DASHBOARD_TOKEN is once accounts are on.
TOKEN_ADMIN = {"id": 0, "nickname": "token-admin", "role": "admin", "can_create_city": True, "label": ""}

#: The only static trees the console loads. Everything else under the repo root
#: (source, dashboard_config.json, data/, residents' memory under output/) is
#: read through the API or not at all.
STATIC_PREFIXES = ("/site/", "/docs/", "/video/public/", "/output/population/")

#: Root-level documents the 文档 panel lists (site/dashboard/docs.js).
STATIC_FILES = frozenset(("/README.zh-CN.md", "/AGENTS.md", "/CHANGELOG.md"))


#: ``/play/<world id>``: the short link a teacher shows the class (a phone
#: opens the world's 多人共玩 page without the console's world switcher).
PLAY_LINK_RE = re.compile(r"^/play/(w[0-9a-f]{8})/?$")


def _static_path_allowed(path):
    if PLAY_LINK_RE.match(path):
        return True
    if path in STATIC_ROUTES or path in STATIC_FILES or path.startswith(STATIC_PREFIXES):
        return True
    # Traces and avatars: the live run, archived runs and every scenario /
    # parallel world keep them in a `visualization` dir (see replay_runs).
    parts = [part for part in path.split("/") if part]
    return len(parts) > 2 and parts[0] == "output" and "visualization" in parts[1:-1]


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "GAWorldDashboard/0.1"

    # -- access control ---------------------------------------------------
    #
    # Static files are served from the repo root, so without a filter `/.env`
    # (live API keys) and `/.git/` are one GET away — and the deployment guide
    # binds 0.0.0.0. Dot-paths are therefore refused unconditionally.
    #
    # Setting GAWORLD_DASHBOARD_TOKEN turns on a token for *every* request
    # (API and static). Taken from the environment, not dashboard_config.json,
    # because `POST /api/config` can rewrite that file. Browsers log in once
    # with `/?token=…`, which sets an HttpOnly, SameSite=Strict cookie (so the
    # console's own fetches and the SSE stream keep working, and other sites
    # cannot ride it); scripts send `Authorization: Bearer …`.

    AUTH_COOKIE = "gaworld_token"
    user = None
    accounts = None

    def _deny(self, status, message):
        if self.path.startswith("/api/"):
            return self._json_response({"error": message}, status=status)
        data = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # Accounts (gaworld/accounts) layer on top: once the account database
    # exists, a request without the token needs a `gaworld_session` cookie,
    # and gaworld.accounts.policy decides what that user may call. The token
    # holder stays an admin, so operator scripts keep working.

    def _guard(self, path, query):
        """Return True when the request was answered here (refused/redirected).

        Leaves ``self.user`` (None, a user row, or TOKEN_ADMIN) and
        ``self.accounts`` (the store, or None in single-user mode) behind.
        """
        self.user = None
        self.accounts = None
        self.cluster_node = None
        _WORLD.set(None)
        _USER.set(None)
        runs.LOCAL_PORT["port"] = self.server.server_port
        # Readiness exposes no user data and works with either authentication mode.
        if path == "/api/health" and self.command in ("GET", "HEAD"):
            return False
        try:
            self.accounts = accounts.enabled_store(paths.REPO_ROOT)
        except accounts.AccountConfigurationError:
            self._deny(503, "Account service unavailable; contact the administrator")
            return True
        from gaworld.apps import cluster_api

        if cluster_api.is_node_path(path):
            # A node of a distributed world: its token is its whole identity
            # and reaches only its own world's node endpoints.
            header = self.headers.get("Authorization", "")
            bearer = header[7:].strip() if header.lower().startswith("bearer ") else ""
            found = cluster_api.authenticate(bearer) if bearer else None
            if found is None:
                self._deny(401, "节点令牌无效或已被吊销")
                return True
            self.cluster_node = found
            _WORLD.set(found[0])
            return False
        if not path.startswith("/api/") and (
            any(part.startswith(".") for part in path.split("/") if part) or not _static_path_allowed(path)
        ):
            self._deny(404, "Not found")
            return True
        token = os.environ.get("GAWORLD_DASHBOARD_TOKEN", "").strip()
        if not token and self.accounts is None:
            return False
        if token:
            verdict = self._token_ok(path, query, token)
            if verdict == "answered":
                return True
            if verdict == "ok":
                self.user = TOKEN_ADMIN
                return self._enter_world(path)
        if self.accounts is None:
            self._deny(401, "authentication required: open /?token=<token> or send Authorization: Bearer <token>")
            return True
        morsel = SimpleCookie(self.headers.get("Cookie", "")).get(accounts_api.SESSION_COOKIE)
        self.user = self.accounts.session_user(morsel.value) if morsel is not None else None
        if self.user is not None:
            LAST_SEEN[self.user["id"]] = time.time()
        if self.user is not None and self._enter_world(path):
            return True
        level = access_policy.required(self.command, path)
        if access_policy.allows(self.user, level, paths.current_world()):
            return False
        if self.user is not None:
            self._deny(403, DENIALS[level])
        elif path.startswith("/api/"):
            self._deny(401, "请先登录：/login")
        else:
            target = path + (f"?{query}" if query else "")
            self._redirect("/login?" + urlencode({"next": target}))
        return True

    def _enter_world(self, path):
        """Make the cookie's world the request's active world, if this user may
        see it (else the shared default). Returns True when the request was
        refused here: a static path into a world the user may not see."""
        if self.accounts is None:
            return False
        _USER.set(self.user)
        # Judge the path by its non-empty segments, the way translate_path
        # resolves the file: `/output//worlds/…` serves the same file.
        parts = [part for part in path.split("/") if part]
        if parts[:2] == ["output", "worlds"]:
            target = self.accounts.get_world(parts[2]) if len(parts) > 2 else None
            if target is None or not world_readable(target, self.user):
                self._deny(404, "Not found")
                return True
        morsel = SimpleCookie(self.headers.get("Cookie", "")).get(WORLD_COOKIE)
        if morsel is not None and worlds.valid_id(morsel.value):
            world = self.accounts.get_world(morsel.value)
            if world is not None and world_readable(world, self.user):
                _WORLD.set(world)
        return False

    def _token_ok(self, path, query, token):
        """"ok" when the request carries the operator token, "answered" when a
        `?token=` login was handled here (redirect or refusal), else "no"."""
        params = parse_qs(query, keep_blank_values=True)
        offered = (params.pop("token", [""]) or [""])[0]
        if offered:
            if not hmac.compare_digest(offered, token):
                self._deny(401, "invalid token")
                return "answered"
            rest = urlencode(params, doseq=True)
            self.send_response(303)
            self.send_header(
                "Set-Cookie",
                f"{self.AUTH_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Location", path + (f"?{rest}" if rest else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return "answered"
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip(), token):
            return "ok"
        morsel = SimpleCookie(self.headers.get("Cookie", "")).get(self.AUTH_COOKIE)
        if morsel is not None and hmac.compare_digest(morsel.value, token):
            return "ok"
        return "no"

    def log_message(self, fmt, *args):
        # The login URL carries the token in its query string; keep it out of logs.
        message = re.sub(r"token=[^&\s]*", "token=***", fmt % args)
        sys.stderr.write(f"{self.address_string()} - - [{self.log_date_time_string()}] {message}\n")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=paths.REPO_ROOT, **kwargs)

    def end_headers(self):
        # The dashboard JS/CSS and trace JSON change between runs; without
        # this, browsers serve stale assets from memory cache indefinitely.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json_response(self, payload, status=200, headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _auth_reply(self, payload, status, set_cookie):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(data)

    def _quota_refusal(self, path):
        """Why a member may not start more model work today, or None.

        A soft quota: only requests that start model calls are refused, and
        work already running finishes.
        """
        user = self.user
        if not access_policy.quota_gated(path) or not user or user.get("role") == "admin":
            return None
        quota = self.accounts.get_setting("daily_llm_calls_per_user", 0)
        if quota <= 0:
            return None
        from gaworld.accounts import usage

        if usage.TALLY.today(user.get("id")) < quota:
            return None
        return f"今天的大模型调用额度（{quota} 次）已用完；明天再来，或请老师调整额度"

    def _city_write_refusal(self, path, payload):
        """Why a non-admin may not make this city write, or None.

        Members with `can_create_city` may create cities and edit the ones
        they created; the creator is recorded in the account database, so a
        city made before accounts existed belongs to the admins.
        """
        store, user = self.accounts, self.user
        if store is None or user is None or user.get("role") == "admin":
            return None
        if path.rstrip("/") == "/api/city/create":
            return "覆盖已有城市需要管理员" if payload.get("force") else None
        from gaworld.city.bundle import resolve_city

        refs = [payload.get("city") or ""]
        if path.rstrip("/") == "/api/city/migrate" and payload.get("from_city"):
            refs.append(payload["from_city"])
        for ref in refs:
            try:
                slug = resolve_city(str(ref)).slug
            except Exception:
                continue  # unknown city: city_api answers 404 with its own message
            if store.city_owner(slug) != user.get("id"):
                return "只能修改自己建立的城市"
        return None

    def _serve_node(self, method, path, payload):
        from gaworld.apps import cluster_api

        world, node = self.cluster_node
        try:
            body, status = cluster_api.handle_node(world, node, method, path, payload, {})
        except Exception as exc:
            _LOG.exception("%s %s (node %s) failed: %s", method, path, node.get("id"), exc)
            return self._json_response({"error": str(exc)}, status=500)
        if isinstance(body, bytes):
            return self._download_response(body, "application/zip", f"{world['id']}.zip")
        return self._json_response(body, status=status)

    def _open_play_link(self, world_id):
        """``/play/<world>``: enter that world and open the 多人共玩 page."""
        target = "/site/dashboard/play.html"
        if self.accounts is None:
            return self._redirect(target)
        world = self.accounts.get_world(world_id)
        if world is None or self.user is None or not world_readable(world, self.user):
            return self._deny(404, "没有这个世界，或它没有对你开放")
        from gaworld.apps import worlds_api

        self.send_response(303)
        self.send_header("Set-Cookie", worlds_api.world_cookie(world_id))
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

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

    def _wrong_method(self, path):
        """Answer 405 when the API document lists *path* under other methods only.

        Paths the document does not know fall through to the handlers as before.
        """
        from gaworld.apps import openapi

        allowed = openapi.allowed_methods(path)
        if not allowed or self.command in allowed:
            return False
        methods = ", ".join(sorted(allowed))
        self._json_response(
            {"error": f"{self.command} is not supported here; use {methods}", "allowed": sorted(allowed)},
            status=405,
            headers={"Allow": methods},
        )
        return True

    def _handle_api_get(self, path, query):
        if path == "/api/cluster":
            from gaworld.apps import cluster_api

            body, status = cluster_api.handle_get(self.user if self.accounts is not None else None, path)
            return self._json_response(body, status=status)
        if path == "/api/play":
            from gaworld.apps import play_api

            body, status = play_api.handle_get(self.user if self.accounts is not None else None, path)
            return self._json_response(body, status=status)
        if path == "/api/worlds" or path.startswith("/api/worlds/"):
            from gaworld.apps import worlds_api

            return self._auth_reply(*worlds_api.handle_get(self.accounts, self.user, path))
        if path.startswith("/api/auth/"):
            return self._auth_reply(*accounts_api.handle_get(self.accounts, self.user, path))
        # Kernel surface: generic interventions + the SSE record stream
        # (gaworld/apps/kernel_api.py). The stream holds the connection open,
        # so it writes to the socket itself instead of returning JSON.
        if path == "/api/openapi.json":
            from gaworld.apps import openapi

            return self._json_response(openapi.spec())
        if path == "/api/events/stream":
            from gaworld.apps import kernel_api

            return kernel_api.serve_stream(self, query)
        # Modules that answer a whole prefix on their own (gaworld/apps/routes.py).
        delegated = routes.dispatch_get(path, query)
        if delegated is not None:
            body, status = delegated
            return self._json_response(body, status=status)
        if path == "/api/config":
            return self._json_response(_config_summary())
        if path == "/api/agents":
            return self._json_response({"agents": residents.agents_summary()})
        if path.startswith("/api/agents/") and path.endswith("/avatar"):
            agent = residents.agent_state(path.split("/")[3])
            if agent is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            data = build_agent_avatar_svg(agent).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/skills":
            return self._json_response({"skills": residents.skills_library()})
        if path.startswith("/api/agents/") and path.endswith("/profile"):
            agent_id = path.split("/")[3]
            profile = residents.agent_profile(agent_id)
            if not profile:
                return self._json_response({"error": "Profile not found"}, status=404)
            return self._json_response(profile)
        if path.startswith("/api/agents/") and path.endswith("/state"):
            agent_id = path.split("/")[3]
            state = residents.agent_state(agent_id)
            if state is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            return self._json_response(state)
        if path.startswith("/api/agents/") and path.endswith("/big5"):
            agent_id = path.split("/")[3]
            data = residents.agent_big5(agent_id)
            if data is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            return self._json_response(data)
        if path.startswith("/api/agents/") and "/autobiography/jobs/" in path:
            from gaworld.apps import autobiography_api
            payload, status = autobiography_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/agents/") and path.endswith("/autobiography"):
            from gaworld.apps import autobiography_api
            payload, status = autobiography_api.handle_get(path, query)
            return self._json_response(payload, status=status)
        if path.startswith("/api/agents/") and path.endswith("/detail"):
            agent_id = path.split("/")[3]
            detail = residents.agent_detail(agent_id)
            if detail is None:
                return self._json_response({"error": "Agent not found"}, status=404)
            return self._json_response(detail)
        if path.startswith("/api/agents/") and path.endswith("/memory"):
            agent_id = path.split("/")[3]
            return self._json_response(residents.memory_payload(agent_id))
        if path.startswith("/api/agents/") and path.endswith("/goals"):
            agent_id = path.split("/")[3]
            return self._json_response(residents.agent_goals_payload(agent_id))
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
            return self._json_response(runs.run_status(int(raw_offset) if raw_offset else None))
        if path == "/api/run/log/export":
            markdown, filename = _run_log_markdown()
            return self._download_response(
                markdown.encode("utf-8"), "text/markdown; charset=utf-8", filename
            )
        if path == "/api/trace/meta":
            return self._json_response(_latest_trace_meta())
        if path == "/api/trace/data":
            return self._json_response(_trace_payload())
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
        store = self.accounts
        if path.startswith("/api/auth/"):
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get(accounts_api.SESSION_COOKIE)
            return self._auth_reply(
                *accounts_api.handle_post(store, self.user, path, payload, morsel.value if morsel else "")
            )
        if store is not None:
            if path != "/api/play/claim":  # lease renewals every 30 s; play_api audits the first claim
                store.audit(self.user, "POST", path)
            refusal = self._quota_refusal(path)
            if refusal:
                return self._json_response({"error": refusal}, status=429)
        if path.startswith("/api/worlds/"):
            from gaworld.apps import worlds_api

            return self._auth_reply(*worlds_api.handle_post(store, self.user, path, payload))
        if path.startswith("/api/cluster/"):
            from gaworld.apps import cluster_api

            body, status = cluster_api.handle_post(self.user if store is not None else None, path, payload, store)
            return self._json_response(body, status=status)
        if path.startswith("/api/play/"):
            from gaworld.apps import play_api

            body, status = play_api.handle_post(self.user if store is not None else None, path, payload, store)
            return self._json_response(body, status=status)
        delegated = routes.dispatch_post(path, payload)
        if delegated is not None:
            body, status = delegated
            return self._json_response(body, status=status)
        if path.startswith("/api/city"):
            from gaworld.apps import city_api

            refusal = self._city_write_refusal(path, payload)
            if refusal:
                return self._json_response({"error": refusal}, status=403)
            body, status = city_api.handle_post(path, payload)
            if store is not None and status == 200:
                route = path.rstrip("/")
                if route == "/api/city/create" and self.user and self.user.get("id"):
                    store.set_city_owner(body["city"]["slug"], self.user["id"])
                elif route == "/api/city/delete":
                    store.forget_city(os.path.basename(str(body.get("removed") or "")))
            return self._json_response(body, status=status)
        if path == "/api/config":
            return self._json_response(_save_config_patch(payload))
        if path == "/api/agents":
            return self._json_response(residents.create_agent(payload))
        if path.startswith("/api/agents/") and path.endswith("/profile"):
            agent_id = path.split("/")[3]
            return self._json_response(residents.save_agent_profile(agent_id, payload.get("text", "")))
        if path.startswith("/api/agents/") and path.endswith("/state"):
            agent_id = path.split("/")[3]
            return self._json_response(residents.save_agent_state(agent_id, payload))
        if path.startswith("/api/agents/") and path.endswith("/big5"):
            agent_id = path.split("/")[3]
            try:
                return self._json_response(residents.save_agent_big5(agent_id, payload))
            except ValueError as exc:
                return self._json_response({"error": str(exc)}, status=400)
        if path.startswith("/api/agents/") and path.endswith("/autobiography"):
            from gaworld.apps import autobiography_api
            body, status = autobiography_api.handle_post(path, payload)
            return self._json_response(body, status=status)
        if path.startswith("/api/agents/") and path.endswith("/goals"):
            agent_id = path.split("/")[3]
            try:
                saved = residents.save_agent_goals_payload(agent_id, payload)
            except ValueError as exc:
                return self._json_response({"error": str(exc)}, status=400)
            return self._json_response(saved)
        if path.startswith("/api/agents/") and path.endswith("/memory"):
            agent_id = path.split("/")[3]
            return self._json_response(residents.append_agent_memory(agent_id, payload))
        if path.startswith("/api/agents/") and path.endswith("/relationships"):
            agent_id = path.split("/")[3]
            return self._json_response(residents.save_agent_relationships(agent_id, payload))
        if path.startswith("/api/agents/") and path.endswith("/finance"):
            agent_id = path.split("/")[3]
            return self._json_response(residents.save_agent_finance(agent_id, payload))
        if path == "/api/run/start":
            return self._json_response(runs.start_simulation(payload))
        if path == "/api/run/stop":
            return self._json_response(runs.stop_simulation())
        if path == "/api/run/schedule":
            return self._json_response(runs.schedule_simulation(payload))
        if path == "/api/run/schedule/cancel":
            return self._json_response(runs.cancel_scheduled_simulation())
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
        if self._guard(path, parsed.query):
            return
        if self.cluster_node is not None:
            return self._serve_node("GET", path, {})
        link = PLAY_LINK_RE.match(path)
        if link:
            return self._open_play_link(link.group(1))
        if path.startswith("/api/"):
            if self._wrong_method(path):
                return
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
        elif path in access_policy.PUBLIC_PAGES:
            self.path = "/site/auth/index.html"
        return super().do_GET()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if self._guard(path, parsed.query):
            return
        if path == "/api/health":
            return self._handle_api_get(path, parse_qs(parsed.query))
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
        elif path in access_policy.PUBLIC_PAGES:
            self.path = "/site/auth/index.html"
        return super().do_HEAD()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if self._guard(path, parsed.query):
            return
        if self.cluster_node is not None:
            from gaworld.apps import cluster_api

            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > cluster_api.MAX_BODY:
                # Read it off the socket anyway (bounded) so the node sees the 413
                # instead of a broken pipe.
                remaining = min(length, 16 * cluster_api.MAX_BODY)
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                self.close_connection = True
                return self._json_response({"error": "请求太大"}, status=413)
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                return self._json_response({"error": str(exc)}, status=400)
            return self._serve_node("POST", path, payload)
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
        if self._wrong_method(path):
            return
        try:
            return self._handle_api_post(path)
        except (ValueError, KeyError) as exc:
            return self._json_response(
                {"error": str(exc)},
                status=400,
            )
        except runs.RunConflict as exc:
            return self._json_response({"error": str(exc)}, status=409)
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
        runs.stop_all_simulations()
        _reset_collaboration_service_for_tests()
        server.server_close()


#: Names that used to live here -> ``(module they moved to, name there)``.
_MOVED = {
    **{name: (paths, target) for name, target in paths.DASHBOARD_ALIASES.items()},
    **{name: (runs, target) for name, target in runs.DASHBOARD_ALIASES.items()},
    **{name: (residents, target) for name, target in residents.DASHBOARD_ALIASES.items()},
}


class _MovedNamesGuard(types.ModuleType):
    """Fails loudly on a name that moved out of this module.

    Reading ``ds.REPO_ROOT`` raises AttributeError naming the new home. So does
    *assigning* it: a plain ``ds.REPO_ROOT = tmp`` would otherwise just create
    an attribute nothing reads, and the code under test would go on using the
    real path.
    """

    def _moved(self, name):
        owner, target = _MOVED[name]
        return AttributeError(f"{self.__name__}.{name} moved to {owner.__name__}.{target}")

    def __getattr__(self, name):
        if name in _MOVED:
            raise self._moved(name)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in _MOVED:
            raise self._moved(name)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in _MOVED:
            raise self._moved(name)
        super().__delattr__(name)


sys.modules[__name__].__class__ = _MovedNamesGuard


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Serve the GAWorld local dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    # Under `python -m` this file runs as `__main__`, while the API modules
    # import `gaworld.apps.dashboard_server` -- a second copy with its own
    # per-request world, run table and queue. Serve from that canonical copy so
    # there is exactly one of each.
    from gaworld.apps import dashboard_server as canonical

    canonical.run_server(host=args.host, port=args.port)
