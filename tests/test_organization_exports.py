"""Completed metric downloads stay within the active world's persisted history."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from gaworld import worlds
from gaworld.accounts import context
from gaworld.apps import openapi, organizations_api, routes, world_paths
from gaworld.organizations.store import OrganizationStore
from tests.test_organization_comparison import make_export

ENDPOINT = "/api/organizations/exports/metrics"


@pytest.fixture
def exported(tmp_path, monkeypatch):
    path, metrics = make_export(tmp_path / "run")
    config = {
        "memory_dir": str(tmp_path / "run" / "memory"),
        "organizations": {"enabled": True, "output_dir": str(path.parent)},
    }
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(world_paths, "DASHBOARD_CONFIG_PATH", str(tmp_path / "dashboard_config.json"))
    Path(world_paths.DASHBOARD_CONFIG_PATH).write_text(json.dumps(config), encoding="utf-8")
    user_token = context.USER.set(None)
    world_token = context.WORLD.set(None)
    yield path, metrics, config
    context.WORLD.reset(world_token)
    context.USER.reset(user_token)


def archive(path, metrics, day=1):
    return path.parent / "generations" / metrics["generation_id"] / f"day-{day}" / "metrics.json"


def test_download_preserves_original_content_hash_and_database(exported, monkeypatch):
    path, metrics, config = exported
    db = Path(config["memory_dir"]) / "organizations.sqlite"
    before_db = db.read_bytes()
    raw = archive(path, metrics).read_bytes()
    monkeypatch.setattr(
        organizations_api, "_store", lambda *args: pytest.fail("export must not open writable store")
    )
    body, status = organizations_api.handle_get(ENDPOINT, {})
    assert status == 200
    assert body["content"].encode("utf-8") == raw
    assert body["sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["generation_id"] == metrics["generation_id"] and body["day"] == 1
    assert body["scope"] == "cumulative_current_generation"
    assert body["filename"] == f"organizations-{metrics['generation_id']}-day-1-metrics.json"
    assert body["content_type"] == "application/json"
    assert db.read_bytes() == before_db


def test_no_completed_run_creates_no_database_or_export_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(world_paths, "DASHBOARD_CONFIG_PATH", str(tmp_path / "dashboard_config.json"))
    world_token = context.WORLD.set(None)
    try:
        assert organizations_api.handle_get(ENDPOINT, {})[1] == 404
        assert not (tmp_path / "output").exists()
    finally:
        context.WORLD.reset(world_token)


def test_new_generation_does_not_serve_stale_latest_file_and_history_remains_readable(exported):
    path, metrics, config = exported
    with_store = OrganizationStore(Path(config["memory_dir"]) / "organizations.sqlite")
    try:
        current = with_store.new_generation()
    finally:
        with_store.close()
    assert current != metrics["generation_id"]
    assert organizations_api.handle_get(ENDPOINT, {})[1] == 404
    assert organizations_api.handle_get(ENDPOINT, {"day": ["1"]})[1] == 404
    body, status = organizations_api.handle_get(ENDPOINT, {"generation_id": [metrics["generation_id"]]})
    assert status == 200 and body["generation_id"] == metrics["generation_id"]
    assert body["content"].encode("utf-8") == archive(path, metrics).read_bytes()


def test_later_incomplete_day_still_exports_previous_completed_day(exported):
    _, metrics, config = exported
    store = OrganizationStore(Path(config["memory_dir"]) / "organizations.sqlite")
    try:
        store.set_meta("open_day", 2)
        store.set_meta("recovery_required", True)
    finally:
        store.close()
    body, status = organizations_api.handle_get(ENDPOINT, {})
    assert status == 200 and body["day"] == 1
    assert body["generation_id"] == metrics["generation_id"]
    assert organizations_api.handle_get(ENDPOINT, {"day": ["2"]})[1] == 404


def test_legacy_history_requires_explicit_day_if_saved_metadata_is_missing(exported):
    _, metrics, config = exported
    db_path = Path(config["memory_dir"]) / "organizations.sqlite"
    store = OrganizationStore(db_path)
    try:
        store.new_generation()
    finally:
        store.close()
    with sqlite3.connect(db_path) as db:
        db.execute("DELETE FROM meta WHERE key=?", (f"generation_state:{metrics['generation_id']}",))
    query = {"generation_id": [metrics["generation_id"]]}
    assert organizations_api.handle_get(ENDPOINT, query)[1] == 404
    body, status = organizations_api.handle_get(ENDPOINT, {**query, "day": ["1"]})
    assert status == 200 and body["day"] == 1


@pytest.mark.parametrize(
    "query",
    [
        {"day": ["0"]},
        {"day": ["-1"]},
        {"day": ["1.5"]},
        {"day": ["true"]},
        {"day": ["1", "2"]},
        {"day": []},
        {"generation_id": ["../other"]},
        {"generation_id": ["a", "b"]},
        {"path": ["/etc/passwd"]},
        {"world_id": ["other"]},
    ],
)
def test_invalid_ambiguous_or_cross_world_queries_are_rejected(exported, query):
    assert organizations_api.handle_get(ENDPOINT, query)[1] == 400


@pytest.mark.parametrize("problem", ["json", "generation", "day", "scope", "nonfinite", "list"])
def test_corrupt_archive_is_rejected_instead_of_serving_latest_fallback(exported, problem):
    path, metrics, _ = exported
    target = archive(path, metrics)
    data = dict(metrics)
    if problem == "json":
        target.write_text("{", encoding="utf-8")
    elif problem == "nonfinite":
        target.write_text('{"coverage":NaN}', encoding="utf-8")
    elif problem == "list":
        target.write_text("[]", encoding="utf-8")
    else:
        data[{"generation": "generation_id", "day": "day", "scope": "scope"}[problem]] = {
            "generation": "other",
            "day": 2,
            "scope": "daily_increment",
        }[problem]
        target.write_text(json.dumps(data), encoding="utf-8")
    body, status = organizations_api.handle_get(ENDPOINT, {})
    assert status == 409 and "error" in body


def test_missing_or_escaping_archive_is_not_downloadable(exported, tmp_path):
    path, metrics, _ = exported
    target = archive(path, metrics)
    target.unlink()
    assert organizations_api.handle_get(ENDPOINT, {})[1] == 404
    other = tmp_path / "other-world-metrics.json"
    other.write_text(json.dumps(metrics), encoding="utf-8")
    target.symlink_to(other)
    assert organizations_api.handle_get(ENDPOINT, {})[1] == 409


@pytest.mark.parametrize("problem", ["file_loop", "directory_loop", "huge_integer"])
def test_unresolvable_paths_and_unparseable_json_are_controlled_errors(exported, problem):
    path, metrics, config = exported
    target = archive(path, metrics)
    db = Path(config["memory_dir"]) / "organizations.sqlite"
    before = db.read_bytes()
    if problem == "file_loop":
        target.unlink()
        target.symlink_to(target.name)
    elif problem == "directory_loop":
        parent = target.parent
        parent.rename(parent.with_name("preserved-day"))
        parent.symlink_to(parent.name, target_is_directory=True)
    else:
        target.write_text('{"value":' + "1" * 5000 + "}", encoding="utf-8")
    assert organizations_api.handle_get(ENDPOINT, {})[1] == 409
    assert db.read_bytes() == before


def test_corrupt_database_is_reported_without_overwriting_it(exported):
    _, _, config = exported
    db = Path(config["memory_dir"]) / "organizations.sqlite"
    db.write_bytes(b"not sqlite")
    assert organizations_api.handle_get(ENDPOINT, {})[1] == 409
    assert db.read_bytes() == b"not sqlite"


def test_actual_world_overrides_isolate_downloads_from_default_and_other_worlds(exported, tmp_path):
    _, default_metrics, _ = exported
    outputs = {}
    for world_id, rule, hiring in [
        ("w0123abcd", "equal_split", "lottery"),
        ("w0123abce", "need_first", "skill_first"),
    ]:
        path, metrics = make_export(tmp_path / f"source-{world_id}", rule, hiring)
        shutil.copytree(path.parent.parent, tmp_path / worlds.root(world_id))
        outputs[world_id] = metrics
    context.USER.set({"id": 9, "role": "member"})
    for world_id, metrics in outputs.items():
        context.WORLD.set({"id": world_id, "owner_id": 7})
        body, status = organizations_api.handle_get(ENDPOINT, {})
        assert status == 200 and body["generation_id"] == metrics["generation_id"]
        assert body["generation_id"] != default_metrics["generation_id"]
        other = next(value for key, value in outputs.items() if key != world_id)
        assert (
            organizations_api.handle_get(
                ENDPOINT,
                {
                    "generation_id": [other["generation_id"]],
                    "day": ["1"],
                },
            )[1]
            == 404
        )


def test_endpoint_is_readonly_documented_and_does_not_shadow_organization_ids(exported):
    assert routes.find(routes.GET_ROUTES, ENDPOINT).module == "organizations_api"
    assert openapi.allowed_methods(ENDPOINT) == {"GET"}
    operation = openapi.spec()["paths"][ENDPOINT]["get"]
    assert {p["name"] for p in operation["parameters"]} == {"generation_id", "day"}
    assert {"200", "400", "404", "409"} <= operation["responses"].keys()
    assert operation["x-gaworld-access"] == "member"
    store = organizations_api._store()
    try:
        for oid in ["exports", "metrics"]:
            store.put("organizations", oid, {"organization_id": oid, "name": oid})
    finally:
        store.close()
    for oid in ["exports", "metrics"]:
        body, status = organizations_api.handle_get(f"/api/organizations/{oid}", {})
        assert status == 200 and body["organization_id"] == oid
