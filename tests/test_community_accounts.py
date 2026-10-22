"""Open registration and account states preserve the invite deployment boundary."""

import concurrent.futures
import json

import pytest

from gaworld.accounts import AccountError, AccountStore


@pytest.fixture
def store(tmp_path):
    instance = AccountStore(str(tmp_path / "accounts.sqlite"))
    instance.init_schema()
    instance.create_user("admin", "correct horse", role="admin")
    return instance


def test_open_registration_requires_configuration_and_verification(store, monkeypatch):
    from gaworld.accounts.community import register_open, verify_email

    delivered = []

    def sender(email, kind, token):
        delivered.append((email, kind, token))

    with pytest.raises(AccountError, match="开放注册"):
        register_open(store, "alice", "correct horse", "a@example.com", "Alice", sender)
    monkeypatch.setenv("GAWORLD_REGISTRATION", "open")
    alice = register_open(store, "alice", "correct horse", "A@example.com", "Alice", sender)
    assert alice["role"] == "member" and not alice["email_verified"]
    assert not alice["can_create_city"]
    assert delivered[0][:2] == ("a@example.com", "verify")
    with store._db() as db:
        assert delivered[0][2] not in json.dumps(
            [dict(row) for row in db.execute("SELECT * FROM account_tokens")]
        )
    assert verify_email(store, delivered[0][2])["email_verified"]
    with pytest.raises(AccountError):
        verify_email(store, delivered[0][2])


def test_invite_accounts_migrate_and_disabled_sessions_stop_working(store):
    from gaworld.accounts.community import set_status

    user = store.register(store.create_invites(1)[0], "legacy", "correct horse")
    assert store.get_user(user["id"])["email_verified"]
    token = store.open_session(user["id"])
    set_status(store, user["id"], enabled=False)
    assert store.session_user(token) is None
    assert store.authenticate("legacy", "correct horse") is None


def test_email_delivery_failure_never_verifies_or_reports_success(store, monkeypatch):
    from gaworld.accounts.community import register_open

    monkeypatch.setenv("GAWORLD_REGISTRATION", "open")

    def unavailable(*args):
        raise AccountError("邮件服务不可用")

    with pytest.raises(AccountError, match="邮件"):
        register_open(store, "alice", "correct horse", "a@example.com", "Alice", unavailable)
    assert not store.authenticate("alice", "correct horse")["email_verified"]


def test_recovery_is_single_use_and_invalidates_sessions(store, monkeypatch):
    from gaworld.accounts.community import recover, register_open, reset_email_password

    monkeypatch.setenv("GAWORLD_REGISTRATION", "open")
    messages = []

    def sender(email, kind, token):
        messages.append((kind, token))

    user = register_open(store, "alice", "correct horse", "a@example.com", "Alice", sender)
    session = store.open_session(user["id"])
    recover(store, "a@example.com", sender)
    reset_email_password(store, messages[-1][1], "new password")
    assert store.session_user(session) is None
    assert store.authenticate("alice", "new password")
    with pytest.raises(AccountError):
        reset_email_password(store, messages[-1][1], "another password")


def test_atomic_model_budget_across_workers(store):
    from gaworld.accounts.community import reserve_call, settle_call

    user = store.create_user("worker", "correct horse")
    store.set_setting("daily_llm_calls_per_user", 2)

    def attempt(_):
        try:
            return reserve_call(store, user["id"])
        except AccountError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        reservations = [r for r in pool.map(attempt, range(6)) if r]
    assert len(reservations) == 2
    settle_call(store, reservations[0], attempted=False)
    assert reserve_call(store, user["id"])


def test_provider_entry_enforces_budget_before_router_call(store, monkeypatch):
    from gaworld.accounts.context import USER
    from gaworld.llm import providers

    monkeypatch.setenv("GAWORLD_ACCOUNTS_DB", store.path)
    store.set_setting("daily_llm_calls_per_user", 1)
    user = store.create_user("caller", "correct horse")
    token = USER.set(user)
    calls = []
    monkeypatch.setattr(providers.LLM_ROUTER, "call", lambda *args, **kwargs: calls.append(1) or "ok")
    try:
        assert providers.call_llm("test") == "ok"
        with pytest.raises(AccountError, match="额度"):
            providers.call_llm("test")
        assert len(calls) == 1
    finally:
        USER.reset(token)


def test_different_rate_limit_windows_do_not_erase_each_other(store):
    from gaworld.accounts.community import rate_limit

    for _ in range(3):
        rate_limit(store, "ip:request", 20, 300)
        rate_limit(store, "email:a@example.com", 3, 3600)
    rate_limit(store, "ip:request", 20, 300)
    with pytest.raises(AccountError, match="频繁"):
        rate_limit(store, "email:a@example.com", 3, 3600)


def test_smtp_uses_verified_tls(monkeypatch):
    import ssl

    from gaworld.accounts import mail

    contexts = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, *, context=None):
            contexts.append(context)

        def send_message(self, message):
            pass

    monkeypatch.setenv("GAWORLD_PUBLIC_URL", "https://gaworld.example")
    monkeypatch.setenv("GAWORLD_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("GAWORLD_MAIL_FROM", "hello@example.com")
    monkeypatch.delenv("GAWORLD_MAIL_MODE", raising=False)
    monkeypatch.setattr(mail.smtplib, "SMTP", SMTP)
    mail.send("alice@example.com", "verify", "token")
    assert contexts[0] is not None
    assert contexts[0].check_hostname and contexts[0].verify_mode == ssl.CERT_REQUIRED


def test_open_deployment_fails_closed_without_initialized_accounts(tmp_path, monkeypatch):
    from gaworld.accounts import AccountConfigurationError, enabled_store

    monkeypatch.setenv("GAWORLD_REGISTRATION", "open")
    monkeypatch.setenv("GAWORLD_ACCOUNTS_DB", str(tmp_path / "absent.sqlite"))
    with pytest.raises(AccountConfigurationError):
        enabled_store(str(tmp_path))


def test_legacy_schema_migration_keeps_a_recoverable_backup(tmp_path):
    import sqlite3

    from gaworld.accounts.store import _SCHEMA, hash_password

    path = str(tmp_path / "old.sqlite")
    with sqlite3.connect(path) as db:
        db.executescript(_SCHEMA)
        db.execute("INSERT INTO users VALUES(1,'legacy',?,'admin',1,'',0)", (hash_password("correct horse"),))
    migrated = AccountStore(path)
    migrated.init_schema()
    assert (tmp_path / "old.sqlite.pre-community.sqlite").exists()
    assert migrated.authenticate("legacy", "correct horse")


def test_mailbox_limit_normalizes_whitespace_before_counting(store, monkeypatch):
    from gaworld.apps import community_auth

    monkeypatch.setattr(community_auth.mail, "send", lambda *args: None)
    for email in ("a@example.com", " a@example.com", "a@example.com "):
        community_auth.post(store, None, "/api/auth/recover", {"email": email}, "")
    with pytest.raises(AccountError, match="频繁"):
        community_auth.post(store, None, "/api/auth/recover", {"email": " a@example.com "}, "")
