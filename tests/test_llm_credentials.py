"""Write-only personal keys: authorization, isolation, rotation and launch gates."""

import concurrent.futures
import contextvars
import json
import os
import stat
from unittest import mock

import pytest

from gaworld.accounts.context import USER
from gaworld.apps import runs, settings_api
from gaworld.llm import credentials
from gaworld.llm.providers import build_provider, probe_provider


@pytest.fixture
def vault(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "private" / "credentials.json"
    monkeypatch.setenv(credentials.ENV_PATH, str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    token = USER.set({"id": 1, "role": "admin"})
    try:
        yield path
    finally:
        USER.reset(token)


@pytest.fixture
def cfg():
    return {"type": "openai", "base_url": "https://test.invalid/v1", "model": "test-model"}


def test_save_rotate_delete(vault, cfg):
    assert credentials.lookup(cfg) is None
    provider = build_provider(cfg)
    credentials.save(cfg, "test-key-one")
    assert provider.api_key == "test-key-one"
    assert stat.S_IMODE(vault.stat().st_mode) == 0o600
    assert stat.S_IMODE(vault.parent.stat().st_mode) == 0o700
    credentials.save(cfg, "test-key-two")
    assert provider.api_key == "test-key-two"
    credentials.save(cfg, None)
    assert provider.api_key is None


def test_endpoint_and_protocol_binding(vault, cfg):
    credentials.save(cfg, "test-key")
    assert credentials.lookup(dict(cfg, model="another-model")) == "test-key"
    for patch in (
        {"base_url": "https://evil.invalid/v1"},
        {"base_url": "https://test.invalid/other-tenant"},
        {"base_url": "http://test.invalid/v1"},
        {"type": "anthropic"},
    ):
        assert credentials.lookup(dict(cfg, **patch)) is None


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://test.invalid",
        "https://key@test.invalid",
        "https://test.invalid?k=1",
        "https://test.invalid/#x",
        "file:///tmp/api",
    ],
)
def test_reject_unsafe_endpoints(vault, cfg, endpoint):
    with pytest.raises(ValueError):
        credentials.save(dict(cfg, base_url=endpoint), "test-key")
    assert not vault.exists()


@pytest.mark.parametrize("key", ["", "key with space", "key\nheader", "x" * 4097, 123])
def test_reject_malformed_key_without_echo(vault, cfg, key):
    with pytest.raises(ValueError) as error:
        credentials.save(cfg, key)
    assert repr(key) not in str(error.value)
    assert not vault.exists()


def test_disabled_and_repository_path(vault, cfg, monkeypatch, tmp_path):
    monkeypatch.delenv(credentials.ENV_PATH)
    assert credentials.lookup(cfg) is None
    with pytest.raises(ValueError):
        credentials.save(cfg, "test-key")
    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / ".git").touch()  # worktrees use a .git file, not a directory
    monkeypatch.setenv(credentials.ENV_PATH, str(repo / "private" / "keys.json"))
    with pytest.raises(ValueError, match="outside"):
        credentials.save(cfg, "test-key")


def test_symlink_and_permissions(vault, cfg, monkeypatch):
    credentials.save(cfg, "test-key")
    vault.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        credentials.lookup(cfg)
    vault.chmod(0o600)
    link = vault.parent / "linked.json"
    link.symlink_to(vault)
    monkeypatch.setenv(credentials.ENV_PATH, str(link))
    with pytest.raises(ValueError, match="symbolic"):
        credentials.save(cfg, "replacement")


def test_corrupt_store_does_not_echo_or_overwrite(vault, cfg):
    credentials.save(cfg, "test-key")
    vault.write_text('{"do-not-echo-this-secret"', encoding="utf-8")
    with pytest.raises(ValueError) as error:
        credentials.save(cfg, "replacement")
    assert "do-not-echo" not in str(error.value)
    assert "do-not-echo" in vault.read_text()


def test_concurrent_writes_preserve_other_providers(vault, cfg):
    def save(index):
        credentials.save(dict(cfg, base_url=f"https://test.invalid/{index}"), f"key-{index}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(contextvars.copy_context().run, save, i) for i in range(16)]
        [future.result() for future in futures]
    assert len(json.loads(vault.read_text())) == 16


@pytest.mark.parametrize("kind", ["openai", "anthropic", "claude"])
def test_personal_mode_never_borrows_environment_key(vault, cfg, monkeypatch, kind):
    cfg = dict(cfg, type=kind, api_key_env="TEST_LEGACY_KEY")
    monkeypatch.setenv("TEST_LEGACY_KEY", "legacy-key")
    credentials.save(cfg, "managed-key")
    provider = build_provider(cfg)
    assert provider.api_key == "managed-key"
    credentials.save(cfg, None)
    assert provider.api_key is None
    assert not credentials.key_ready(cfg)
    assert os.environ["TEST_LEGACY_KEY"] == "legacy-key"


@pytest.mark.parametrize("user", [None, {"role": "admin", "id": None}])
def test_only_authenticated_account_can_save(vault, cfg, user):
    token = USER.set(user)
    try:
        result, status = settings_api.handle_post(
            "/api/settings/llm/credential", {"name": "test", "api_key": "test-key"}
        )
        assert status == 403
        assert "test-key" not in json.dumps(result)
        assert not vault.exists()
    finally:
        USER.reset(token)


@pytest.mark.parametrize("role", ["admin", "member"])
def test_personal_api_never_writes_config_or_returns_key(vault, cfg, role):
    config = {"llm": {"providers": {"test": cfg}}}
    token = USER.set({"id": 1, "role": role})
    try:
        with (
            mock.patch.object(settings_api.world_paths, "effective_config", return_value=config),
            mock.patch.object(settings_api.world_paths, "atomic_write_json") as write_config,
        ):
            for key in ["first-test-key", "replacement-test-key"]:
                result, status = settings_api.handle_post(
                    "/api/settings/llm/credential", {"name": "test", "api_key": key}
                )
                assert status == 200
                assert result["key_ready"] and result["managed_key"]
                assert key not in json.dumps(result)
                overview = settings_api.overview()
                assert key not in json.dumps(overview)
                assert overview["can_manage_credentials"]
            result, status = settings_api.handle_post(
                "/api/settings/llm/credential", {"name": "test", "action": "delete"}
            )
            assert status == 200 and not result["key_ready"]
            write_config.assert_not_called()
    finally:
        USER.reset(token)


def test_provider_probe_redacts_echoed_key(vault, cfg):
    credentials.save(cfg, "do-not-echo-key")
    with mock.patch("gaworld.llm.providers.OpenAIProvider.call", return_value="do-not-echo-key"):
        assert "do-not-echo-key" not in json.dumps(probe_provider(cfg))
    with mock.patch("gaworld.llm.providers.OpenAIProvider.call", side_effect=ValueError("do-not-echo-key")):
        assert "do-not-echo-key" not in json.dumps(probe_provider(cfg))


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_requests_use_saved_key_without_following_redirects(vault, cfg, kind):
    cfg = dict(cfg, type=kind)
    credentials.save(cfg, "test-key")
    response = mock.Mock()
    response.json.return_value = {
        "choices": [{"message": {"content": "OK"}}],
        "content": [{"type": "text", "text": "OK"}],
    }
    with mock.patch("gaworld.llm.providers.requests.post", return_value=response) as post:
        assert probe_provider(cfg)["ok"]
        assert post.call_args.kwargs["allow_redirects"] is False
        assert "test-key" in " ".join(post.call_args.kwargs["headers"].values())


def test_launch_missing_key_fails_before_reset(vault, cfg):
    config = {"llm": {"providers": {"test": cfg}, "routing": {"default": "test"}}}
    with (
        mock.patch.object(runs.paths, "effective_config", return_value=config),
        mock.patch("gaworld.plugins.validate_runtime_config"),
        mock.patch.object(runs.subprocess, "run") as reset,
        mock.patch.object(runs.subprocess, "Popen") as launch,
    ):
        with pytest.raises(ValueError, match="API Key"):
            runs.launch({}, {"reset": True})
        reset.assert_not_called()
        launch.assert_not_called()
    credentials.save(cfg, "test-key")
    credentials.validate_launch(config)


def test_fallback_requires_personal_primary_key_but_legacy_behavior_unchanged(vault, cfg, monkeypatch):
    config = {
        "llm": {
            "providers": {"paid": cfg, "local": {"type": "ollama", "model": "m"}},
            "routing": {"default": "paid", "fallback": ["local"]},
        }
    }
    with pytest.raises(ValueError, match="personal API Key"):
        credentials.validate_launch(config)
    monkeypatch.delenv(credentials.ENV_PATH)
    credentials.validate_launch(config)
    config["llm"]["routing"] = {"default": "local"}
    credentials.validate_launch(config)
    config["llm"]["routing"]["tasks"] = {"schedule": "paid"}
    with pytest.raises(ValueError, match="API Key"):
        credentials.validate_launch(config)


def test_account_isolation_even_for_admin_and_concurrent_calls(vault, cfg):
    provider = build_provider(dict(cfg, api_key="server-key-must-not-be-used"))
    credentials.save(cfg, "admin-private-key")

    def member(index):
        token = USER.set({"id": index + 2, "role": "member"})
        try:
            assert provider.api_key is None
            credentials.save(cfg, f"member-{index}-key")
            assert provider.api_key == f"member-{index}-key"
            credentials.save(cfg, None)
            assert provider.api_key is None
        finally:
            USER.reset(token)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(member, range(16)))
    assert provider.api_key == "admin-private-key"


def test_member_cannot_choose_another_account(vault, cfg):
    config = {"llm": {"providers": {"test": cfg}}}
    with mock.patch.object(settings_api.world_paths, "effective_config", return_value=config):
        _result, status = settings_api.handle_post(
            "/api/settings/llm/credential", {"name": "test", "api_key": "test-key", "user_id": 2}
        )
        assert status == 400
        assert not vault.exists()


def test_identity_reaches_threads_and_child_environment(vault, cfg, monkeypatch):
    from gaworld.accounts.usage import child_env
    from gaworld.core.runner import parallel_map

    credentials.save(cfg, "personal-key")
    assert parallel_map(lambda _: credentials.lookup(cfg), [1, 2, 3], max_workers=3) == ["personal-key"] * 3
    env = child_env({})
    assert env["GAWORLD_USER_ID"] == "1"
    token = USER.set(None)
    try:
        monkeypatch.setenv("GAWORLD_USER_ID", env["GAWORLD_USER_ID"])
        assert build_provider(cfg).api_key == "personal-key"
        monkeypatch.delenv("GAWORLD_USER_ID")
        assert build_provider(dict(cfg, api_key="server-key")).api_key is None
    finally:
        USER.reset(token)


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_missing_personal_key_never_calls_shared_paid_backend(vault, cfg, kind):
    cfg = dict(cfg, type=kind, api_key="server-key-must-not-be-used")
    with mock.patch("gaworld.llm.providers.requests.post") as post:
        with pytest.raises(ValueError, match="API Key"):
            build_provider(cfg).call("test")
        post.assert_not_called()


def test_worker_process_reads_only_its_own_key(vault, cfg):
    import subprocess
    import sys

    from gaworld.accounts.usage import child_env

    credentials.save(cfg, "dummy-process-test-key")
    code = "from gaworld.llm.credentials import lookup; import json; import sys; assert bool(lookup(json.loads(sys.argv[1]))) == (sys.argv[2] == 'yes')"
    env = child_env(os.environ.copy())
    subprocess.run([sys.executable, "-c", code, json.dumps(cfg), "yes"], env=env, check=True, timeout=20)
    env["GAWORLD_USER_ID"] = "2"
    subprocess.run([sys.executable, "-c", code, json.dumps(cfg), "no"], env=env, check=True, timeout=20)
