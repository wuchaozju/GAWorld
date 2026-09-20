"""Guard against the parallel-run race on shared atomic-write temp files.

compare-event runs the with_event / without_event scenarios as two parallel
subprocesses. Both bootstrap growth profiles and work capabilities into the
*same* global cache path. A shared "{path}.tmp" made one process's os.replace
rename the temp out from under the other -> FileNotFoundError crash. The temp
filename must be process-unique.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import gaworld.interests as interests
import gaworld.work.capabilities as capabilities


class TestProcessUniqueTmp(unittest.TestCase):
    def _assert_unique_tmp(self, module, save_fn, payload):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(os.path.basename(src))
            return real_replace(src, dst)

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            with patch.object(module.os, "replace", side_effect=spy):
                with patch.object(module.os, "getpid", return_value=111):
                    save_fn(path, payload)
                with patch.object(module.os, "getpid", return_value=222):
                    save_fn(path, payload)
            # distinct temp names for the two "processes" -> no os.replace race
            self.assertEqual(len(set(seen)), 2, f"temp names collided: {seen}")
            self.assertTrue(os.path.exists(path))
            leftovers = [f for f in os.listdir(d) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [], f"leftover temp files: {leftovers}")

    def test_growth_cache_tmp_is_process_unique(self):
        self._assert_unique_tmp(interests, interests.save_growth_cache, {})

    def test_capabilities_cache_tmp_is_process_unique(self):
        self._assert_unique_tmp(capabilities, capabilities.save_cache, {})


if __name__ == "__main__":
    unittest.main()
