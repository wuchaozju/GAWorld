"""
Tests that pin where LLMClient.chat() writes its traffic log (llm_traffic.jsonl).

Goal of the pinned behaviour: the traffic log must never silently land in the
current working directory (the historic footgun that created a 1.4 GB blob in
the repo root). With no configuration it must go to
$FOS_DATA_DIR/llm_traffic.jsonl, or to $HOME/work/fos-data/llm_traffic.jsonl
when FOS_DATA_DIR is unset too. FOS_LLM_LOG stays the explicit override, "off"
still disables logging, parent directories are auto-created, and a failed
log write is surfaced instead of swallowed.

Every test drives a real LLMClient.chat() call against the offline mock
dialect with the LLM transport stubbed, so no network or real data directory
is ever touched. HOME / FOS_DATA_DIR are monkeypatched to pytest tmp dirs.

Environment is applied and then fos.core.llm.client is reloaded, so the tests
work whether the implementation reads the environment at import time or at
call time.

Contains: TestDefaultLocation, TestFosDataDirOverride, TestExplicitOverride,
TestOffDisables, TestEmptyStringFallback, TestParentDirCreation,
TestWriteFailureSurfaced, TestNeverInsideSourceCheckout
"""

import importlib
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from fos.core.llm_config import LLMConfig

# Marker echoed back by the stubbed transport; it must appear in the log line.
_MARKER = "TRAFFIC-LOG-OK"
# Marker embedded in the user message; it must appear in the logged messages.
_PAYLOAD = "MARKER-1358-payload"


def _mock_config() -> LLMConfig:
    """Return an offline mock-dialect config for LLMClient."""
    return LLMConfig(
        dialect="mock",
        api_key="",
        model="mock",
        base_url=None,
        temperature=0.1,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        max_tokens=256,
    )


def _ready_client(monkeypatch, *, env, cwd):
    """
    Apply env vars, chdir to an isolated tmp dir, reload client module.

    env maps variable name -> value; value None means "remove the variable".
    cwd is a per-test tmp dir: every chat() runs away from the real repo root
    so a cwd-relative log default (the current bug) can never pollute it.
    Returns (client_module, LLMClient) so callers can patch the module.
    """
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)

    import fos.core.llm.client as client_mod

    importlib.reload(client_mod)  # re-capture env for import-time implementations

    client = client_mod.LLMClient(_mock_config())
    client.max_retries = 0
    client.retry_backoff_s = 0.0
    # Stub the transport: offline, deterministic, echoes the marker.
    client.client.chat = lambda msgs, json_mode=False: _MARKER
    return client_mod, client


def _run_chat(monkeypatch, *, env, cwd) -> str:
    """Run one stubbed mock chat() under the given env; return the LLM text."""
    client_mod, client = _ready_client(monkeypatch, env=env, cwd=cwd)
    with patch.object(
        client_mod,
        "_get_openai",
        return_value={
            "normalize_messages_for_openai": lambda msgs, vision, safe: msgs
        },
    ):
        return client.chat([{"role": "user", "content": _PAYLOAD}])


def _assert_traffic_logged(log_file: Path) -> None:
    """Assert log_file exists and holds one traffic line with both markers."""
    assert log_file.exists(), (
        "traffic log file missing at expected location: " + str(log_file)
    )
    content = log_file.read_text(encoding="utf-8")
    assert _MARKER in content, f"traffic log line missing raw_result in {log_file}"
    assert _PAYLOAD in content, f"traffic log line missing the user message in {log_file}"


class TestDefaultLocation:
    """Both FOS_LLM_LOG and FOS_DATA_DIR unset -> $HOME/work/fos-data."""

    def test_default_path_is_home_fos_data_not_cwd(self, tmp_path, monkeypatch):
        # Contract pinned: default resolves via expanduser($HOME)/work/fos-data.
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        _run_chat(
            monkeypatch,
            env={"HOME": str(home), "FOS_LLM_LOG": None, "FOS_DATA_DIR": None},
            cwd=cwd,
        )
        expected = home / "work" / "fos-data" / "llm_traffic.jsonl"
        _assert_traffic_logged(expected)
        # The old cwd-relative default must be gone for good.
        assert not (cwd / "llm_traffic.jsonl").exists(), (
            "traffic log must not fall back to a cwd-relative llm_traffic.jsonl"
        )


class TestFosDataDirOverride:
    """FOS_DATA_DIR set -> <FOS_DATA_DIR>/llm_traffic.jsonl."""

    def test_fos_data_dir_override_wins_over_home_default(self, tmp_path, monkeypatch):
        # Contract pinned: FOS_DATA_DIR takes precedence over $HOME/work/fos-data.
        data_dir = tmp_path / "data"
        home = tmp_path / "home"
        _run_chat(
            monkeypatch,
            env={
                "FOS_DATA_DIR": str(data_dir),
                "HOME": str(home),
                "FOS_LLM_LOG": None,
            },
            cwd=tmp_path / "cwd",
        )
        expected = data_dir / "llm_traffic.jsonl"
        _assert_traffic_logged(expected)
        home_fallback = home / "work" / "fos-data" / "llm_traffic.jsonl"
        assert not home_fallback.exists(), (
            "FOS_DATA_DIR must take precedence over the $HOME/work/fos-data fallback"
        )


class TestExplicitOverride:
    """FOS_LLM_LOG explicit absolute path is honored exactly (regression guard)."""

    def test_explicit_fos_llm_log_is_honored_exactly(self, tmp_path, monkeypatch):
        explicit = tmp_path / "explicit.jsonl"
        _run_chat(
            monkeypatch,
            env={"FOS_LLM_LOG": str(explicit), "FOS_DATA_DIR": None},
            cwd=tmp_path / "cwd",
        )
        _assert_traffic_logged(explicit)


class TestOffDisables:
    """FOS_LLM_LOG=off (any casing) disables traffic logging (regression guard)."""

    @pytest.mark.parametrize("off_value", ["off", "OFF", "Off"])
    def test_off_disables_logging(self, tmp_path, monkeypatch, off_value):
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        _run_chat(
            monkeypatch,
            env={
                "FOS_LLM_LOG": off_value,
                "HOME": str(home),
                "FOS_DATA_DIR": None,
            },
            cwd=cwd,
        )
        leftovers = [str(p) for p in tmp_path.rglob("llm_traffic.jsonl")]
        assert leftovers == [], (
            f"FOS_LLM_LOG={off_value!r} must disable logging, "
            f"but found: {leftovers}"
        )


class TestEmptyStringFallback:
    """FOS_LLM_LOG="" behaves exactly like unset -> fos-data default."""

    def test_empty_string_uses_home_fos_data_default(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        _run_chat(
            monkeypatch,
            env={"FOS_LLM_LOG": "", "HOME": str(home), "FOS_DATA_DIR": None},
            cwd=cwd,
        )
        expected = home / "work" / "fos-data" / "llm_traffic.jsonl"
        _assert_traffic_logged(expected)
        assert not (cwd / "llm_traffic.jsonl").exists(), (
            "empty FOS_LLM_LOG must not resolve to a cwd-relative file"
        )


class TestParentDirCreation:
    """Parent dirs of the log path are auto-created before appending."""

    def test_missing_parent_directories_are_created(self, tmp_path, monkeypatch):
        target = tmp_path / "a" / "b" / "llm_traffic.jsonl"
        assert not target.parent.exists()  # precondition: parents missing
        _run_chat(
            monkeypatch,
            env={"FOS_LLM_LOG": str(target), "FOS_DATA_DIR": None},
            cwd=tmp_path / "cwd",
        )
        _assert_traffic_logged(target)


class TestWriteFailureSurfaced:
    """An unwritable log path is surfaced, not silently swallowed."""

    def test_write_failure_is_not_silent(self, tmp_path, monkeypatch, caplog):
        # Parent is a regular file, so <parent>/llm_traffic.jsonl can never be
        # opened for append. Pinned contract: the failure is either logged
        # (any logger, WARNING+) or raised with a message naming the log path.
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file, not a directory", encoding="utf-8")
        target = blocker / "llm_traffic.jsonl"

        client_mod, client = _ready_client(
            monkeypatch,
            env={"FOS_LLM_LOG": str(target), "FOS_DATA_DIR": None},
            cwd=tmp_path / "cwd",
        )
        with patch.object(
            client_mod,
            "_get_openai",
            return_value={
                "normalize_messages_for_openai": lambda msgs, vision, safe: msgs
            },
        ), caplog.at_level(logging.WARNING):
            try:
                client.chat([{"role": "user", "content": _PAYLOAD}])
            except Exception as exc:  # surfaced-by-raising is acceptable
                message = f"{type(exc).__name__}: {exc}"
                assert "traffic" in message.lower() or "llm" in message.lower(), (
                    "raised error does not point at the traffic log: " + message
                )
                return
        relevant = [
            r.getMessage()
            for r in caplog.records
            if "traffic" in r.getMessage().lower()
            or "llm" in r.getMessage().lower()
            or str(target) in r.getMessage()
        ]
        assert relevant, (
            "unwritable traffic-log path was swallowed silently; "
            "expected a logged warning/error naming the traffic log"
        )


class TestNeverInsideSourceCheckout:
    """Default log path never lands inside a source checkout (integration guard)."""

    def test_default_path_never_inside_source_checkout(self, tmp_path, monkeypatch):
        # Models the historic footgun: process cwd is the repo root with an
        # existing llm_traffic.jsonl blob, and FOS vars are unset. Traffic must
        # still go to $HOME/work/fos-data, never into the checkout.
        fake_repo = tmp_path / "source-checkout"
        fake_repo.mkdir()
        preexisting = fake_repo / "llm_traffic.jsonl"
        sentinel = "preexisting sentinel line\n"
        preexisting.write_text(sentinel, encoding="utf-8")

        home = tmp_path / "home"
        _run_chat(
            monkeypatch,
            env={"HOME": str(home), "FOS_LLM_LOG": None, "FOS_DATA_DIR": None},
            cwd=fake_repo,
        )
        assert preexisting.read_text(encoding="utf-8") == sentinel, (
            "default traffic logging must not append into a source checkout root"
        )
        expected = home / "work" / "fos-data" / "llm_traffic.jsonl"
        _assert_traffic_logged(expected)
