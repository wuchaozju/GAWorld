"""Owned organization-method versions for the cooperation picker."""

from __future__ import annotations

from gaworld.collaboration.organization_methods import method_hash, normalize_method
from gaworld.research.organization_intelligence.comparison.store import Store

PREFIX = "/api/collaboration/organization-methods"


def database():
    from gaworld.apps.organization_comparison_api import root

    return Store(root() / "methods")


def resolve(identifier, version):
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


def handle_get(path, query=None):
    suffix = path[len(PREFIX) :].strip("/")
    try:
        if not suffix:
            return {"methods": database().list("M")}, 200
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
