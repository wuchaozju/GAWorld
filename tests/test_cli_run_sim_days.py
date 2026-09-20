from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import generative_city_sim as sim


class TestCliRunSimDays(unittest.TestCase):
    def test_run_command_overrides_sim_days(self) -> None:
        original_config_sim_days = sim.CONFIG["sim_days"]
        original_sim_days = sim.SIM_DAYS
        self.addCleanup(sim.CONFIG.__setitem__, "sim_days", original_config_sim_days)
        self.addCleanup(setattr, sim, "SIM_DAYS", original_sim_days)

        args = SimpleNamespace(command="run", sim_days=3)

        with patch.object(sim, "_build_arg_parser") as build_parser, patch.object(
            sim, "run_simulation"
        ) as run_simulation:
            build_parser.return_value.parse_args.return_value = args

            sim._main()

        self.assertEqual(3, sim.CONFIG["sim_days"])
        self.assertEqual(3, sim.SIM_DAYS)
        run_simulation.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
