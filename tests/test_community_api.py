"""End-to-end HTTP checks of visitor reads, account writes and private sources."""

import json

import pytest

from gaworld.apps import world_paths
from gaworld.research import workbench
from tests import test_accounts as account_support

PASSWORD = account_support.PASSWORD


@pytest.fixture
def host(monkeypatch, request):
    server = account_support.HttpTest()
    server.setUp()
    request.addfinalizer(server.tearDown)
    store = account_support._store(server.tmp.name)
    server.admin = store.create_user("admin", PASSWORD, role="admin")
    server.alice = store.create_user("alice", PASSWORD)
    server.bob = store.create_user("bob", PASSWORD)
    server.ac = server._login("alice")
    server.bc = server._login("bob")
    server.dc = server._login("admin")
    monkeypatch.setattr(world_paths, "REPO_ROOT", server.tmp.name)
    from pathlib import Path

    monkeypatch.setattr(workbench, "PROJECT_ROOT", Path(server.tmp.name))
    server.store = store
    return server


def test_public_pages_are_anonymous_but_private_console_is_not(host):
    # Public HTML is served from the actual checkout (switch root back for this check).
    from pathlib import Path

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(world_paths, "REPO_ROOT", str(Path(__file__).resolve().parents[1]))
        for path in ("/explore", "/plaza", "/publications/example", "/people/example", "/register"):
            assert host._req("GET", path)[0].status == 200, path
        for path in (
            "/console",
            "/workspace?view=publish",
            "/site/community/workspace.html?view=notifications",
        ):
            for method in ("GET", "HEAD"):
                assert host._req(method, path)[0].status == 303, (method, path)
                assert host._req(method, path, cookie=host.ac)[0].status == 200, (method, path)
        for path in ("/site/community/navigation.js", "/explore?q=study", "/publications/example?version=1"):
            for method in ("GET", "HEAD"):
                assert host._req(method, path)[0].status == 200, (method, path)
    assert host._req("GET", "/api/community/publications")[0].status == 200
    assert host._req("GET", "/api/workspace/overview")[0].status == 401
    assert host._req("POST", "/api/community/posts", {"title": "bad", "body": "bad"})[0].status == 401


def test_publish_comment_and_withdraw_over_http(host):
    resp, draft = host._req(
        "POST",
        "/api/community/drafts",
        {"title": "Study", "body": "Public report", "license": "read_only"},
        cookie=host.ac,
    )
    assert resp.status == 200, draft
    resp, item = host._req(
        "POST",
        "/api/community/publish",
        {"draft_id": draft["id"], "revision": draft["revision"]},
        cookie=host.ac,
    )
    assert resp.status == 200, item
    path = "/api/community/publications/" + item["id"]
    assert host._req("GET", path)[0].status == 200
    resp, _ = host._req(
        "POST",
        "/api/community/comments",
        {"target_type": "publication", "target_id": item["id"], "version": 1, "body": "Question"},
        cookie=host.bc,
    )
    assert resp.status == 200
    assert host._req("POST", "/api/community/withdraw", {"id": item["id"]}, cookie=host.bc)[0].status == 400
    assert host._req("POST", "/api/community/withdraw", {"id": item["id"]}, cookie=host.ac)[0].status == 200
    assert host._req("GET", path)[0].status == 404


def test_foreign_origin_and_wrong_world_are_rejected(host):
    assert (
        host._req(
            "POST",
            "/api/community/posts",
            {"title": "Forged", "body": "bad"},
            cookie=host.ac,
            headers={"Origin": "https://foreign.example"},
        )[0].status
        == 403
    )
    assert (
        host._req(
            "POST", "/api/research/analyze", {}, cookie=host.ac, headers={"X-GAWorld-World": "wffffffff"}
        )[0].status
        == 409
    )


def test_source_requires_ownership_and_revision_and_fork_is_a_private_draft(host):
    plan = workbench.ResearchPlan.from_dict(
        {
            "id": "20261021-120000-abcdef",
            "title": "Source",
            "kind": "idea",
            "material": "Question",
            "steps": [],
            "designs": [],
            "provider": "private-model",
            "language": "zh-CN",
            "created_at": "2026-10-21",
        }
    )
    workbench.save_plan(plan, {"owner_id": host.alice["id"], "world_id": ""})
    source = {"kind": "plan", "id": plan.id}
    assert host._req("POST", "/api/community/source", source, cookie=host.bc)[0].status == 400
    resp, preview = host._req("POST", "/api/community/source", source, cookie=host.ac)
    assert resp.status == 200, preview
    assert "private-model" not in json.dumps(preview)
    resp, draft = host._req(
        "POST",
        "/api/community/drafts",
        {
            "title": "Shared",
            "body": "Public",
            "license": "CC-BY-4.0",
            "include_template": True,
            "source": {**source, "revision": preview["revision"]},
        },
        cookie=host.ac,
    )
    assert resp.status == 200, draft
    resp, item = host._req(
        "POST",
        "/api/community/publish",
        {"draft_id": draft["id"], "revision": draft["revision"]},
        cookie=host.ac,
    )
    assert resp.status == 200, item
    resp, copied = host._req(
        "POST", "/api/community/fork", {"id": item["id"], "version": 1, "world_id": ""}, cookie=host.bc
    )
    assert resp.status == 200, copied
    stored = workbench.load_plan(copied["plan_id"])
    assert stored["owner_id"] == host.bob["id"] and not stored.get("provider")
    assert stored["provenance"]["publication_id"] == item["id"]
    assert not stored.get("runs")


def test_auth_request_size_is_bounded_before_reading_body(host):
    response, _ = host._req("POST", "/api/auth/login", {}, headers={"Content-Length": "99999999"})
    assert response.status == 413
