"""An unseeded run draws a seed and records it, so it can be repeated.

An unseeded run used to leave ``random_seed: null`` in its manifest, so it
could never be repeated. ``_resolve_run_seed`` keeps such a run exactly as
random (the seed comes from OS entropy) but installs it in CONFIG, where the
economy / travel / kernel RNGs derive from it, and the manifest records it.
"""

from __future__ import annotations

import unittest
from unittest import mock

import pytest

import generative_city_sim as sim

pytestmark = pytest.mark.slow


class ResolveRunSeedTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sim.CONFIG, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        sim.CONFIG.pop("random_seed", None)
        seed_patch = mock.patch.object(sim, "_AUTO_SEED", None)
        seed_patch.start()
        self.addCleanup(seed_patch.stop)

    def test_configured_seed_wins(self):
        with mock.patch.object(sim, "RANDOM_SEED", 42):
            self.assertEqual((42, "config"), sim._resolve_run_seed())

    def test_seed_set_on_config_after_import_is_respected(self):
        sim.CONFIG["random_seed"] = 7
        with mock.patch.object(sim, "RANDOM_SEED", None):
            self.assertEqual((7, "config"), sim._resolve_run_seed())

    def test_unseeded_run_draws_and_installs_a_seed(self):
        with mock.patch.object(sim, "RANDOM_SEED", None):
            seed, source = sim._resolve_run_seed()
        self.assertEqual("auto", source)
        self.assertIsInstance(seed, int)
        self.assertEqual(seed, sim.CONFIG["random_seed"])

    def test_a_second_unseeded_run_does_not_reuse_the_first_draw(self):
        with mock.patch.object(sim, "RANDOM_SEED", None), \
                mock.patch.object(sim.random.SystemRandom, "randrange", side_effect=[11, 22]):
            self.assertEqual((11, "auto"), sim._resolve_run_seed())
            self.assertEqual((22, "auto"), sim._resolve_run_seed())


if __name__ == "__main__":
    unittest.main()
