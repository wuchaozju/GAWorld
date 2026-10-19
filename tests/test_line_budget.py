"""The simulator's main file and main loop may only shrink.

``generative_city_sim.py`` grew from 1,380 lines of ``run_simulation`` (when
the extraction plan in ``docs/RUN_SIMULATION_EXTRACTION_PLAN.md`` was shelved) to 2,285. The
budgets in ``tests/line_budget.json`` are upper bounds: going over fails, and
going 50+ lines under fails too, asking for the bound to be lowered, so room
freed by moving code out cannot quietly fill up again.
"""

from __future__ import annotations

import ast
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGET_PATH = os.path.join(ROOT, "tests", "line_budget.json")
#: How far under its bound a count may drift before the bound must come down.
SLACK = 50


def _budgets():
    with open(BUDGET_PATH, encoding="utf-8") as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}


def _measure(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        source = fh.read()
    functions = {
        node.name: node.end_lineno - node.lineno + 1
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return len(source.splitlines()), functions


class LineBudgetTest(unittest.TestCase):
    def _check(self, what, count, bound):
        self.assertLessEqual(
            count,
            bound,
            f"{what} is {count} lines, over its budget of {bound}: move code out "
            "(docs/RUN_SIMULATION_EXTRACTION_PLAN.md) instead of adding to it",
        )
        self.assertGreater(
            count,
            bound - SLACK,
            f"{what} is down to {count} lines: lower its budget in tests/line_budget.json "
            f"from {bound} to {count} so the room cannot fill up again",
        )

    def test_files_and_main_functions_stay_within_budget(self):
        for path, budget in _budgets().items():
            lines, functions = _measure(path)
            with self.subTest(path=path):
                self._check(path, lines, int(budget["lines"]))
            for name, bound in (budget.get("functions") or {}).items():
                with self.subTest(path=path, function=name):
                    self.assertIn(name, functions, f"{name} is no longer a top-level function of {path}")
                    self._check(f"{path}:{name}", functions[name], int(bound))


if __name__ == "__main__":
    unittest.main()
