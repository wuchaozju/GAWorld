"""Configured resource limits reject admission without stopping existing work."""

import pytest

from gaworld.accounts import AccountError, AccountStore


def test_world_limit_is_atomic(tmp_path):
    store = AccountStore(str(tmp_path / "accounts.sqlite"))
    store.init_schema()
    user = store.create_user("alice", "correct horse")
    store.set_setting("max_worlds_per_user", 1)
    store.create_world(user["id"], "one")
    with pytest.raises(AccountError, match="世界数量"):
        store.create_world(user["id"], "two")


def test_public_draft_storage_limit_and_user_independence(tmp_path):
    from gaworld.community.store import CommunityStore

    accounts = AccountStore(str(tmp_path / "accounts.sqlite"))
    accounts.init_schema()
    alice = accounts.create_user("alice", "correct horse")
    bob = accounts.create_user("bob", "correct horse")
    accounts.set_setting("max_community_storage_mb_per_user", 1)
    store = CommunityStore(accounts)
    for _ in range(5):
        store.draft(alice, {"title": "Study", "body": "字" * 65000})
    with pytest.raises(ValueError, match="存储"):
        store.draft(alice, {"title": "Study", "body": "字" * 65000})
    assert store.draft(bob, {"title": "Study", "body": "字" * 65000})


def test_editing_comments_cannot_bypass_storage_budget(tmp_path):
    from gaworld.accounts.resources import community_storage
    from gaworld.community.store import CommunityStore

    accounts = AccountStore(str(tmp_path / "accounts.sqlite"))
    accounts.init_schema()
    alice = accounts.create_user("alice", "correct horse")
    accounts.set_setting("max_community_storage_mb_per_user", 1)
    store = CommunityStore(accounts)
    item = store.post(alice, {"title": "Question", "body": "text", "category": "question"})
    for _ in range(5):
        store.draft(alice, {"title": "Study", "body": "字" * 65000})
    comment = store.comment(alice, {"target_type": "post", "target_id": item["id"], "body": "x"})
    with pytest.raises(ValueError, match="存储"):
        for _ in range(30):
            store.edit_comment(alice, comment["id"], "字" * 5000)
    with accounts._db() as db:
        assert community_storage(db, alice["id"]) <= 1024 * 1024
