"""GAWorld-Rubric-Bench (Track R) — rubric-as-reward evaluation harness.

Design: ../GAWORLD_RUBRIC_BENCH.md
Entry point: ../rubric_bench.py
"""

from .runner import load_rubric, run

__all__ = ["run", "load_rubric"]
