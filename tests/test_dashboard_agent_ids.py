"""Tests for /api/config's agent_ids parsing — particularly the
'first N residents' shorthand that the field hint advertises.

The frontend sends agentIdsInput.value as a raw string ("12" or
"1,2,3"). ``_save_config_patch`` parses that into a list of ints
so the simulation runner can pick its roster. A single-digit input
used to be parsed as ``[12]`` rather than ``range(1, 13)``, leaving
the runner with one agent instead of twelve.
"""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gaworld.apps import dashboard_server


def _reload_with_temp_config(temp_dir: Path):
    """Reimport the module so ``DASHBOARD_CONFIG_PATH`` points at the temp
    file. Cached attributes (``_CACHED_CONFIG``, ``_CACHED_MTIME``) need to
    be wiped too — otherwise the test reads the wrong config file.
    """
    cfg = temp_dir / "dashboard_config.json"
    cfg.write_text("{}", encoding="utf-8")
    if hasattr(dashboard_server, "_CACHED_CONFIG"):
        dashboard_server._CACHED_CONFIG = None
        dashboard_server._CACHED_MTIME = None
    return importlib.reload(dashboard_server)


class AgentIdsParseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._original_path = dashboard_server.DASHBOARD_CONFIG_PATH
        # Replace the config path before the helper reloads.
        dashboard_server.DASHBOARD_CONFIG_PATH = (
            Path(self._tmp.name) / "dashboard_config.json"
        )
        self._mod = _reload_with_temp_config(Path(self._tmp.name))

    def tearDown(self):
        dashboard_server.DASHBOARD_CONFIG_PATH = self._original_path
        _reload_with_temp_config(Path(self._tmp.name).parent)

    def _save(self, payload):
        return self._mod._save_config_patch(payload)

    def test_single_digit_string_expands_to_range(self):
        """'12' means agents 1..12, per the field hint."""
        result = self._save({"agent_ids": "12"})
        self.assertEqual(result["agent_ids"], list(range(1, 13)))

    def test_csv_string_is_preserved(self):
        result = self._save({"agent_ids": "1,2,3"})
        self.assertEqual(result["agent_ids"], [1, 2, 3])

    def test_csv_string_with_spaces_is_trimmed(self):
        result = self._save({"agent_ids": "1, 2, 3"})
        self.assertEqual(result["agent_ids"], [1, 2, 3])

    def test_explicit_list_is_passed_through(self):
        result = self._save({"agent_ids": [7, 8]})
        self.assertEqual(result["agent_ids"], [7, 8])

    def test_empty_string_yields_empty_list(self):
        """An empty input is the 'use all residents' sentinel — leave
        agent_ids empty rather than silently expanding to range(1, 1).
        """
        result = self._save({"agent_ids": ""})
        self.assertEqual(result["agent_ids"], [])

    def test_non_digit_string_falls_back_to_split(self):
        """Garbage in the field is parsed token-by-token; tokens that
        aren't integers are dropped. 'a,3,b' yields [3] rather than
        crashing on the field.
        """
        result = self._save({"agent_ids": "a,3,b"})
        self.assertEqual(result["agent_ids"], [3])