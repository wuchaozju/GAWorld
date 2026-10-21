"""GAWorld-integrated FOS launcher (scripts/start_fos_integrated.sh) contract.

RED phase (task 2773): the launcher script does not exist yet. The integrated
runtime must start the FOS backend on loopback with single-user mode enabled
*only in that backend process's env* — standalone FOS deployments
(fos/README.md, docker-compose) must stay multi-user (``single_user_mode`` off
by default). See docs/FOS_Integration.md §4 and RESULT-2771 §3/§5.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "scripts" / "start_fos_integrated.sh"


def _logical_commands(text: str) -> list[list[str]]:
    """Split a shell script into tokenised logical command lists.

    Strips comments, splits on newlines / ``;`` / ``&&`` / ``||`` so that
    ``VAR=x cmd`` prefixes stay attached to their command. Line continuations
    are joined first. This is a semantic parse, not a raw substring grep.
    """
    text = text.replace("\\\n", " ")
    commands: list[list[str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        for chunk in re.split(r";|&&|\|\|", line):
            chunk = chunk.strip()
            if chunk:
                try:
                    commands.append(shlex.split(chunk))
                except ValueError:  # unbalanced quote — still counts as a command
                    commands.append(chunk.split())
    return commands


def _mentions_var(tokens: list[str], name: str) -> bool:
    """True if the command sets ``name=...`` as a prefix or via ``env``/``export``."""
    for tok in tokens:
        if tok == name or tok.startswith(f"{name}="):
            return True
        if tok in ("export", "env"):
            continue
        if "=" in tok and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            break
    return False


def _var_value(tokens: list[str], name: str) -> str | None:
    for tok in tokens:
        m = re.match(rf"^(?:env |export )?{name}=(.*)$", tok)
        if m:
            return m.group(1).strip("'\"")
    return None


@pytest.fixture(scope="module")
def launcher_commands():
    if not LAUNCHER.exists():
        pytest.fail("RED: scripts/start_fos_integrated.sh missing")
    return _logical_commands(LAUNCHER.read_text(encoding="utf-8"))


def _backend_commands(commands):
    return [
        c for c in commands if any("uvicorn" in tok or tok.endswith("main:app") for tok in c)
    ]


class TestIntegratedLauncherExists:
    def test_launcher_script_exists(self):
        assert LAUNCHER.exists(), (
            "RED: scripts/start_fos_integrated.sh does not exist yet — "
            "the GAWorld-integrated FOS launcher has not been implemented"
        )


class TestLauncherSingleUserLoopback:
    def test_script_launches_the_fos_backend(self, launcher_commands):
        assert _backend_commands(launcher_commands), (
            "RED: launcher does not start the FOS backend (uvicorn main:app)"
        )

    def test_backend_launched_with_single_user_mode_true(self, launcher_commands):
        for cmd in _backend_commands(launcher_commands):
            assert _mentions_var(cmd, "FOS_SINGLE_USER_MODE"), (
                "RED: the FOS backend command does not set FOS_SINGLE_USER_MODE in its env"
            )
            assert _var_value(cmd, "FOS_SINGLE_USER_MODE") == "true", (
                "RED: FOS_SINGLE_USER_MODE is not 'true' for the backend process"
            )

    def test_backend_binds_loopback_not_wildcard(self, launcher_commands):
        backend_cmds = _backend_commands(launcher_commands)
        assert backend_cmds, "RED: launcher does not start the FOS backend"
        for cmd in backend_cmds:
            if "--host" in cmd:
                host = cmd[cmd.index("--host") + 1]
                assert host in ("127.0.0.1", "localhost"), (
                    f"RED: backend binds {host!r}, expected loopback (127.0.0.1)"
                )
            assert _var_value(cmd, "FOS_BACKEND_HOST") not in ("0.0.0.0", "::"), (
                "RED: FOS_BACKEND_HOST is set to a non-loopback address"
            )

    def test_no_remote_bind_escape_hatch(self, launcher_commands):
        for cmd in launcher_commands:
            value = _var_value(cmd, "FOS_SINGLE_USER_ALLOW_REMOTE_BIND")
            assert value != "true", (
                "RED: launcher sets FOS_SINGLE_USER_ALLOW_REMOTE_BIND=true — "
                "the integrated launcher must not allow remote bind"
            )


class TestStandaloneDefaultStaysMultiUser:
    def test_settings_single_user_mode_defaults_false(self, monkeypatch):
        """GUARD: the standalone default must stay multi-user (login required)."""
        import os

        for key in [k for k in os.environ if k.startswith("FOS_")]:
            monkeypatch.delenv(key, raising=False)
        from fos.backend.core.config import Settings

        settings = Settings(_env_file=None)
        assert settings.single_user_mode is False, (
            "RED: standalone Settings().single_user_mode must default to False"
        )
