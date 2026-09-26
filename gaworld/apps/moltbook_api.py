"""Dashboard backend for the Moltbook card in Agent Studio.

A delegate module in the ``city_api`` / ``persona_api`` mould: the dashboard
server forwards ``/api/moltbook/*`` here and gains four lines, not a subsystem.

Three operations:

- ``GET  /api/moltbook/agent?id=<n>`` — the switch, the claim state and the
  recorded actions for one resident.
- ``POST /api/moltbook/toggle`` ``{agent_id, enabled, name?}`` — flip the
  switch. Turning it on for a resident without an account registers one on
  Moltbook (the one network call this module makes on its own) and returns the
  claim link the operator has to open; turning it off keeps the account.
- ``POST /api/moltbook/refresh`` ``{agent_id}`` — re-ask Moltbook whether the
  account has been claimed.

The api key never leaves the process: every response is built from
:func:`accounts.public_view`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from gaworld.moltbook import accounts
from gaworld.moltbook import log as action_log
from gaworld.moltbook.client import DEFAULT_BASE_URL, MoltbookClient, MoltbookError

REPO_ROOT = str(Path(__file__).resolve().parents[2])

#: Rows the card shows. The file keeps everything.
RECENT = 20

#: Loose on purpose — Moltbook owns the real rule and says so in its error.
#: This only stops whitespace and empty names from making a round trip.
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


# ---------------------------------------------------------------------------
# Wiring — each resolved per call so the tests can patch them
# ---------------------------------------------------------------------------


def _cfg():
    from gaworld.settings import CONFIG

    return dict(CONFIG.get("moltbook", {}) or {})


def _abs(path):
    text = str(path or "")
    return text if os.path.isabs(text) else os.path.join(REPO_ROOT, text)


def _accounts_path():
    return _abs(_cfg().get("accounts_path") or accounts.DEFAULT_PATH)


def _log_dir():
    return _abs(_cfg().get("log_dir") or action_log.DEFAULT_DIR)


def _client(api_key=""):
    cfg = _cfg()
    return MoltbookClient(
        base_url=cfg.get("base_url") or DEFAULT_BASE_URL,
        api_key=api_key,
        timeout=float(cfg.get("timeout_seconds") or 20),
    )


def _agent_identity(agent_id):
    """``{id, name, age, residence, …}`` from the running city, or ``None``."""
    from gaworld.apps import dashboard_server

    return dashboard_server._agent_state(agent_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first(query, key):
    value = (query or {}).get(key)
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def _agent_id_of(value):
    try:
        agent_id = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("agent_id must be an integer") from None
    if agent_id <= 0:
        raise ValueError("agent_id must be positive")
    return agent_id


def _profile_url(cfg, name):
    if not name:
        return ""
    base = str(cfg.get("base_url") or DEFAULT_BASE_URL)
    origin = base.split("/api/")[0].rstrip("/")
    return f"{origin}/u/{name}"


def _view(agent_id):
    cfg = _cfg()
    record = accounts.get(agent_id, path=_accounts_path()) or accounts.blank(agent_id)
    rows = action_log.load(agent_id, root=_log_dir())
    view = accounts.public_view(record)
    view.update(
        {
            "agent_id": agent_id,
            "actions": list(reversed(rows[-RECENT:])),
            "action_count": len(rows),
            "log_path": os.path.relpath(action_log.path_for(agent_id, root=_log_dir()), REPO_ROOT),
            "profile_url": _profile_url(cfg, record.get("name")),
            "default_name": _default_name(agent_id),
        }
    )
    return view


def _default_name(agent_id):
    return f"gaworld_{int(agent_id)}"


def _description(identity, agent_id):
    if not identity:
        return f"Resident #{agent_id} of GAWorld, a generative city simulation."
    return (
        f"{identity.get('name', '')}, {identity.get('age', '')}, lives in {identity.get('residence', '')}. "
        "A resident of GAWorld, a generative city simulation — this account posts what the "
        "resident did on each simulated day."
    )


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


def handle_get(path, query):
    if path == "/api/moltbook/agent":
        try:
            agent_id = _agent_id_of(_first(query, "id"))
        except ValueError as exc:
            return {"error": str(exc)}, 400
        return _view(agent_id), 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path, payload):
    payload = payload if isinstance(payload, dict) else {}
    if path == "/api/moltbook/toggle":
        return _toggle(payload)
    if path == "/api/moltbook/refresh":
        return _refresh(payload)
    return {"error": "Unknown endpoint"}, 404


def _toggle(payload):
    try:
        agent_id = _agent_id_of(payload.get("agent_id"))
    except ValueError as exc:
        return {"error": str(exc)}, 400
    path = _accounts_path()
    if not payload.get("enabled"):
        accounts.set_enabled(agent_id, False, path=path)
        return _view(agent_id), 200

    identity = _agent_identity(agent_id)
    if identity is None:
        return {"error": f"Unknown agent id {agent_id}"}, 404
    record = accounts.get(agent_id, path=path)
    if not (record and record.get("api_key")):
        name = str(payload.get("name") or "").strip() or _default_name(agent_id)
        if not _NAME_RE.match(name):
            return {"error": "Moltbook name: letters, digits, '_', '-' or '.', 1–64 characters"}, 400
        try:
            result = _client().register(name, _description(identity, agent_id))
        except MoltbookError as exc:
            action_log.append(
                agent_id,
                {
                    "kind": "error", "ok": False,
                    "summary": f"注册 Moltbook 账号 {name} 失败：{exc}",
                    "detail": {"op": "register", "name": name, "http_status": exc.status},
                },
                root=_log_dir(),
            )
            return {"error": f"Moltbook registration failed: {exc}"}, 502
        accounts.save_registration(
            agent_id,
            name=result["name"],
            api_key=result["api_key"],
            claim_url=result["claim_url"],
            verification_code=result["verification_code"],
            path=path,
        )
        action_log.append(
            agent_id,
            {
                "kind": "register", "ok": True,
                "summary": f"注册了 Moltbook 账号 {result['name']}，等待认领",
                "detail": {"name": result["name"], "claim_url": result["claim_url"]},
            },
            root=_log_dir(),
        )
    accounts.set_enabled(agent_id, True, path=path)
    return _view(agent_id), 200


def _refresh(payload):
    try:
        agent_id = _agent_id_of(payload.get("agent_id"))
    except ValueError as exc:
        return {"error": str(exc)}, 400
    path = _accounts_path()
    record = accounts.get(agent_id, path=path)
    if not (record and record.get("api_key")):
        return {"error": "This resident has no Moltbook account yet"}, 409
    try:
        status = _client(record["api_key"]).status()["status"]
    except MoltbookError as exc:
        action_log.append(
            agent_id,
            {
                "kind": "error", "ok": False,
                "summary": f"查询账号状态失败：{exc}",
                "detail": {"op": "status", "http_status": exc.status},
            },
            root=_log_dir(),
        )
        return {"error": f"Moltbook status check failed: {exc}"}, 502
    accounts.set_status(agent_id, status, path=path)
    if status == accounts.STATUS_CLAIMED:
        summary = f"账号 {record.get('name', '')} 已认领"
    else:
        summary = f"账号 {record.get('name', '')} 状态为 {status}"
    action_log.append(
        agent_id,
        {"kind": "status", "ok": True, "summary": summary, "detail": {"status": status}},
        root=_log_dir(),
    )
    return _view(agent_id), 200
