"""Per-agent Moltbook accounts: the switch, the key, the claim state.

One JSON file keyed by agent id. The api key is stored as issued because the
simulator needs it to post; :func:`public_view` is the only shape that leaves
the process over HTTP and it carries a masked hint instead of the key.

Turning the switch off keeps the record. Moltbook names are unique and an
account cannot be re-registered under the same name, so forgetting the key
would strand the account; re-enabling just flips the flag back.
"""

from __future__ import annotations

import json
import os
import threading
import time

DEFAULT_PATH = "data/moltbook_accounts.json"

STATUS_UNREGISTERED = "unregistered"
STATUS_PENDING = "pending_claim"
STATUS_CLAIMED = "claimed"

_LOCK = threading.RLock()


def _load(path):
    if not os.path.exists(path):
        return {"agents": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"agents": {}}
    if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
        return {"agents": {}}
    return data


def _save(data, path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def blank(agent_id):
    return {
        "agent_id": int(agent_id),
        "enabled": False,
        "name": "",
        "api_key": "",
        "claim_url": "",
        "verification_code": "",
        "status": STATUS_UNREGISTERED,
        "registered_at": None,
        "checked_at": None,
    }


def _record(data, agent_id):
    """The live record for ``agent_id`` inside ``data``, created if missing."""
    key = str(int(agent_id))
    record = data["agents"].get(key)
    if not isinstance(record, dict):
        record = blank(agent_id)
        data["agents"][key] = record
        return record
    for field, default in blank(agent_id).items():
        record.setdefault(field, default)
    return record


def get(agent_id, path=DEFAULT_PATH):
    """A copy of the agent's record, or ``None`` when it has never been touched."""
    with _LOCK:
        data = _load(path)
        record = data["agents"].get(str(int(agent_id)))
        if not isinstance(record, dict):
            return None
        return dict(_record(data, agent_id))


def set_enabled(agent_id, enabled, path=DEFAULT_PATH):
    with _LOCK:
        data = _load(path)
        record = _record(data, agent_id)
        record["enabled"] = bool(enabled)
        _save(data, path)
        return dict(record)


def save_registration(agent_id, *, name, api_key, claim_url="", verification_code="", path=DEFAULT_PATH):
    """Store what Moltbook handed back at registration. Status starts pending."""
    with _LOCK:
        data = _load(path)
        record = _record(data, agent_id)
        record.update(
            {
                "name": str(name),
                "api_key": str(api_key),
                "claim_url": str(claim_url or ""),
                "verification_code": str(verification_code or ""),
                "status": STATUS_PENDING,
                "registered_at": time.time(),
            }
        )
        _save(data, path)
        return dict(record)


def set_status(agent_id, status, path=DEFAULT_PATH):
    with _LOCK:
        data = _load(path)
        record = _record(data, agent_id)
        record["status"] = str(status or "unknown")
        record["checked_at"] = time.time()
        _save(data, path)
        return dict(record)


def connected(path=DEFAULT_PATH):
    """``{agent_id: record}`` for every agent whose switch is on and that holds a key."""
    with _LOCK:
        data = _load(path)
    out = {}
    for key, record in data["agents"].items():
        if not isinstance(record, dict):
            continue
        if not (record.get("enabled") and record.get("api_key")):
            continue
        try:
            out[int(key)] = dict(record)
        except (TypeError, ValueError):
            continue
    return out


def mask_key(api_key):
    text = str(api_key or "")
    if len(text) <= 8:
        return "•" * len(text)
    return text[:4] + "…" + text[-4:]


def public_view(record):
    """The record as the browser may see it: everything but the key."""
    if not record:
        return None
    view = {key: value for key, value in record.items() if key != "api_key"}
    view["has_key"] = bool(record.get("api_key"))
    view["api_key_hint"] = mask_key(record.get("api_key")) if record.get("api_key") else ""
    return view
