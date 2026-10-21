"""GAWorld-integrated FOS mode: standalone-default guard.

The integrated backend lifecycle now lives in Python
(`gaworld/apps/fos_supervisor.py`, spawned by `gaworld dashboard`); its
contract is covered by `tests/test_fos_supervisor.py`. This module keeps the
one invariant that must never regress: standalone FOS
(`fos/README.md`, `fos/docker-compose.yml`) stays multi-user
(`single_user_mode` off by default, normal login required).
"""

from __future__ import annotations

import pytest


class TestStandaloneDefaultStaysMultiUser:
    def test_settings_single_user_mode_defaults_false(self, monkeypatch):
        """GUARD: the standalone default must stay multi-user (login required)."""
        import os

        for key in [k for k in os.environ if k.startswith("FOS_")]:
            monkeypatch.delenv(key, raising=False)
        from fos.backend.core.config import Settings

        settings = Settings(_env_file=None)
        assert settings.single_user_mode is False, (
            "standalone Settings().single_user_mode must default to False"
        )
