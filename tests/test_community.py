"""Public versions, discussions and forks never widen the private research ACL."""

import json

import pytest

from gaworld.accounts import AccountStore


@pytest.fixture
def community(tmp_path):
    from gaworld.community.store import CommunityStore

    accounts = AccountStore(str(tmp_path / "accounts.sqlite"))
    accounts.init_schema()
    users = [
        accounts.create_user(name, "correct horse", role=role)
        for name, role in [("alice", "member"), ("bob", "member"), ("admin", "admin")]
    ]
    return CommunityStore(accounts), users


def publish(store, user, **extra):
    draft = store.draft(
        user,
        {"title": "Shared study", "body": "Safe report", "kind": "plan", "license": "CC-BY-4.0", **extra},
    )
    return store.publish(user, draft["id"], draft["revision"])


def test_publication_versions_are_immutable_and_private_fields_excluded(community):
    store, (alice, bob, _) = community
    first = publish(store, alice, api_key="PRIVATE", owner_id=bob["id"])
    assert first["author_id"] == alice["id"]
    assert "PRIVATE" not in json.dumps(store.publication(first["id"]))
    draft = store.draft(
        alice,
        {"publication_id": first["id"], "title": "New version", "body": "Revised", "license": "CC-BY-4.0"},
    )
    second = store.publish(alice, draft["id"], draft["revision"])
    assert second["version"] == 2
    assert store.publication(first["id"], 1)["title"] == "Shared study"
    with pytest.raises(ValueError):
        store.draft(bob, {"publication_id": first["id"], "title": "Stolen", "body": "bad"})


def test_draft_revision_idempotency_and_withdrawal(community):
    store, (alice, _, _) = community
    draft = store.draft(alice, {"title": "Study", "body": "Report"})
    with pytest.raises(ValueError):
        store.publish(alice, draft["id"], "stale revision")
    first = store.publish(alice, draft["id"], draft["revision"])
    assert store.publish(alice, draft["id"], draft["revision"])["version"] == first["version"]
    store.withdraw(alice, first["id"])
    assert store.publication(first["id"]) is None
    assert not store.publications()
    assert store.mine(alice)


def test_comments_bind_versions_and_permissions(community):
    store, (alice, bob, admin) = community
    item = publish(store, alice)
    parent = store.comment(
        bob, {"target_type": "publication", "target_id": item["id"], "version": 1, "body": "Question"}
    )
    reply = store.comment(
        alice,
        {
            "target_type": "publication",
            "target_id": item["id"],
            "version": 1,
            "parent_id": parent["id"],
            "body": "Reply",
        },
    )
    assert reply["version"] == 1
    with pytest.raises(ValueError):
        store.edit_comment(alice, parent["id"], "overwrite")
    store.edit_comment(bob, parent["id"], "Edited")
    store.delete_comment(bob, parent["id"])
    assert store.comments("publication", item["id"])[0]["body"] == "评论已删除"
    store.moderate(admin, "publication", item["id"], "lock", "Keep discussion focused")
    with pytest.raises(ValueError):
        store.comment(
            bob, {"target_type": "publication", "target_id": item["id"], "version": 1, "body": "blocked"}
        )


def test_notifications_and_bookmarks_hide_withdrawn_content(community):
    store, (alice, bob, _) = community
    item = publish(store, alice)
    store.bookmark(bob, "publication", item["id"], True)
    store.bookmark(bob, "publication", item["id"], True)
    store.comment(
        bob,
        {
            "target_type": "publication",
            "target_id": item["id"],
            "version": 1,
            "body": "Private after withdrawal",
        },
    )
    assert len(store.bookmarks(bob)) == 1
    assert store.notifications(alice)
    store.withdraw(alice, item["id"])
    assert not store.bookmarks(bob)
    assert not store.notifications(alice)


def test_replies_cannot_cross_targets_or_versions(community):
    store, (alice, bob, _) = community
    a, b = publish(store, alice), publish(store, alice)
    parent = store.comment(
        bob, {"target_type": "publication", "target_id": a["id"], "version": 1, "body": "A"}
    )
    with pytest.raises(ValueError):
        store.comment(
            bob,
            {
                "target_type": "publication",
                "target_id": b["id"],
                "version": 1,
                "parent_id": parent["id"],
                "body": "Wrong target",
            },
        )


def test_guest_cannot_write_and_read_only_license_cannot_fork(community):
    store, (alice, _, _) = community
    with pytest.raises(ValueError):
        store.draft(None, {"title": "anonymous", "body": "not allowed"})
    item = publish(store, alice, license="read_only")
    with pytest.raises(ValueError):
        store.fork_payload(alice, item["id"], 1)


def test_attachment_whitelist_and_withdrawal(community):
    store, (alice, _, _) = community
    item = publish(
        store, alice, attachments=[{"name": "report.md", "text": "Public report", "mime": "text/markdown"}]
    )
    attachment = store.publication(item["id"])["attachments"][0]
    assert store.attachment(item["id"], 1, attachment["id"])["text"] == "Public report"
    with pytest.raises(ValueError):
        publish(store, alice, attachments=[{"name": "../secret", "path": "/.env", "mime": "text/html"}])
    store.withdraw(alice, item["id"])
    assert store.attachment(item["id"], 1, attachment["id"]) is None


def test_post_report_and_scoped_moderator(community):
    store, (alice, bob, admin) = community
    post = store.post(
        alice, {"title": "How to compare seeds?", "body": "Methods question", "category": "question"}
    )
    report = store.report(bob, "post", post["id"], "Please review")
    assert report["id"]
    with pytest.raises(ValueError):
        store.moderate(bob, "post", post["id"], "hide", "unprivileged")
    store.moderate(admin, "post", post["id"], "hide", "Resolved")
    assert store.get_post(post["id"]) is None


def test_source_status_cannot_be_promoted_to_completed(community):
    store, (alice, _, _) = community
    draft = store.draft(
        alice,
        {"title": "Unrun", "body": "Nothing ran", "kind": "study", "result_status": "completed"},
        source={"kind": "plan", "result_status": "plan", "revision": "hash"},
    )
    assert draft["result_status"] == "plan" and draft["kind"] == "plan"
    manual = store.draft(alice, {"title": "Manual", "body": "No source", "result_status": "completed"})
    assert manual["result_status"] == "plan"


def test_moderator_cannot_republish_author_withdrawn_content(community):
    store, (alice, _, admin) = community
    item = publish(store, alice)
    store.withdraw(alice, item["id"])
    for action in ("restore", "hide"):
        with pytest.raises(ValueError):
            store.moderate(admin, "publication", item["id"], action, "Cannot undo author withdrawal")
    assert store.publication(item["id"]) is None


def test_reusable_template_requires_explicit_public_consent(community):
    store, (alice, bob, _) = community
    source = {"kind": "plan", "result_status": "plan", "template": {"title": "Private design detail"}}
    draft = store.draft(
        alice, {"title": "Redacted title", "body": "Only public text", "license": "CC-BY-4.0"}, source=source
    )
    item = store.publish(alice, draft["id"], draft["revision"])
    assert not item["reusable"]
    assert "Private design detail" not in json.dumps(item)
    with pytest.raises(ValueError):
        store.fork_payload(bob, item["id"], 1)
    explicit = store.draft(
        alice,
        {"title": "Shared design", "body": "Public", "license": "CC-BY-4.0", "include_template": True},
        source=source,
    )
    shared = store.publish(alice, explicit["id"], explicit["revision"])
    assert shared["public_template"] == source["template"]


def test_community_reads_do_not_require_write_transactions(community):
    store, (alice, _, _) = community
    publish(store, alice)
    from unittest.mock import patch

    with patch("gaworld.accounts.community.migrate", side_effect=AssertionError("read reran migration")):
        from gaworld.community.store import CommunityStore

        reader = CommunityStore(store.accounts)
        assert reader.publications()


def test_operator_admin_can_moderate_but_cannot_author_as_id_zero(community):
    store, (alice, _, _) = community
    item = publish(store, alice)
    token_admin = {"id": 0, "role": "admin"}
    store.moderate(token_admin, "publication", item["id"], "lock", "operator moderation")
    assert store.publication(item["id"])["locked"]
    with pytest.raises(ValueError):
        store.draft(token_admin, {"title": "Unaudited", "body": "no account"})


def test_author_cannot_bypass_takedown_by_withdrawing_then_republishing(community):
    store, (alice, _, admin) = community
    item = publish(store, alice)
    store.moderate(admin, "publication", item["id"], "hide", "moderation hold")
    store.withdraw(alice, item["id"])
    draft = store.draft(alice, {"publication_id": item["id"], "title": "Bypass", "body": "same content"})
    with pytest.raises(ValueError):
        store.publish(alice, draft["id"], draft["revision"])
    assert store.publication(item["id"]) is None
