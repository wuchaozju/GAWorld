"""Owned organization-method versions for the cooperation picker."""

from __future__ import annotations

from gaworld.collaboration.organization_methods import (
    BUILTIN_VERSION,
    KINDS,
    VERSION,
    builtin_id,
    builtin_method,
    method_hash,
    normalize_method,
    parse_builtin,
    topology_text,
)
from gaworld.research.organization_intelligence.comparison.store import Store

PREFIX = "/api/collaboration/organization-methods"


def database():
    from gaworld.apps.organization_comparison_api import root

    return Store(root() / "methods")


def builtin_entries():
    """The basic organization methods, ready to be picked by structure.

    Their role slots are not fixed: a built-in method is sized when a task
    starts, so the team that runs it decides how many roles exist. The empty
    ``roles`` list below marks a template, not a runnable method.
    """
    entries = []
    for kind, name in KINDS.items():
        entries.append(
            {
                "id": builtin_id(kind),
                "name": name,
                "version": BUILTIN_VERSION,
                "builtin": True,
                "slots": None,
                "description": topology_text(kind),
                "method": {
                    "version": VERSION,
                    "name": name,
                    "roles": [],
                    "topology": {"kind": kind},
                    "rounds": 0 if kind == "independent" else 2,
                },
                "method_hash": None,
                "evidence": {"verdict": "builtin", "scope": "内置基本组织方式，未在本题上验证"},
            }
        )
    return entries


def resolve(identifier, version, slots=None):
    """The method behind an id: a saved version, or a built-in sized now."""
    kind = parse_builtin(identifier)
    if kind is not None:
        if type(version) is not int or version != BUILTIN_VERSION:
            raise ValueError("组织方式版本不存在，请刷新后重新选择")
        count = int(slots or 0)
        if not 2 <= count <= 12:
            raise ValueError("内置组织方式需要 2–12 位成员")
        method = builtin_method(kind, count)
        return {
            "id": identifier,
            "name": method["name"],
            "version": BUILTIN_VERSION,
            "builtin": True,
            "method": method,
            "method_hash": method_hash(method),
            "description": method["description"],
            "evidence": {"verdict": "builtin", "scope": "内置基本组织方式，未在本题上验证"},
        }
    record = database().get(identifier)
    if type(version) is not int or version != record["version"]:
        raise ValueError("组织方式版本不存在，请刷新后重新选择")
    if method_hash(record["method"]) != record["method_hash"]:
        raise ValueError("组织方式内容校验失败")
    return record


def save_study(study, payload):
    method = normalize_method(study["protocol"]["candidate"])
    # Preserve exactly the tested rules. Library display names are independent.
    return database().create(
        "M",
        {
            "name": str(payload.get("name") or method["name"])[:120],
            "version": 1,
            "method": method,
            "method_hash": method_hash(method),
            "description": str(payload.get("description") or method["description"])[:2000],
            "evidence": {
                "study_id": study["id"],
                "status": study["status"],
                "verdict": study["analysis"].get("verdict", "incomplete"),
                "model": study["protocol"]["model"],
                "benchmark": study["protocol"]["benchmark"]["name"],
                "members": len(study["protocol"]["members"]),
                "scope": "仅在该模型、人数与题库范围内测试；其他任务属于未验证配置",
            },
        },
    )


def _entry(record):
    """One list entry: a saved record says how many roles it runs with."""
    return {
        **record,
        "builtin": bool(record.get("builtin")),
        "slots": len((record.get("method") or {}).get("roles") or []),
    }


def _includes_builtins(query):
    """Whether the caller asked for the basic organization methods as well."""
    raw = (query or {}).get("include")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    return str(raw or "").strip().lower() in {"builtin", "builtins", "all"}


def handle_get(path, query=None):
    suffix = path[len(PREFIX) :].strip("/")
    try:
        if not suffix:
            methods = [_entry(record) for record in database().list("M")]
            if _includes_builtins(query):
                methods = builtin_entries() + methods
            return {"methods": methods}, 200
        return database().get(suffix), 200
    except LookupError as exc:
        return {"error": str(exc)}, 404


def handle_post(path, payload):
    suffix = path[len(PREFIX) :].strip("/")
    try:
        if not isinstance(payload, dict):
            raise ValueError("需要JSON对象")
        previous = database().get(suffix) if suffix else None
        method = normalize_method(payload["method"])
        return database().create(
            "M",
            {
                "name": method["name"],
                "method": method,
                "method_hash": method_hash(method),
                "version": previous["version"] + 1 if previous else 1,
                "previous_id": previous["id"] if previous else None,
                "description": method["description"],
                "evidence": {"verdict": "incomplete", "scope": "此版本尚未验证"},
            },
        ), 201
    except LookupError as exc:
        return {"error": str(exc)}, 404
    except (ValueError, TypeError, KeyError) as exc:
        return {"error": str(exc)}, 400
