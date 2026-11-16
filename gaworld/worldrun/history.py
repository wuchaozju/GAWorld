"""Completed-day state-history persistence (``state/agent_state_history.csv``).

The state history is an ANALYSIS output, never checkpoint truth. Rows are
appended at the same boundary as day-boundary checkpoints — after a day has
fully completed — so an interrupted run keeps the history of the days it did
finish and a resumed run appends exactly the next days, without duplication
or loss. The schema is the legacy one (``agent_id,step,metric,value``) and
stays that way: every reader (``read_state_series``, PW analysis, Phase 7
comparison) consumes it unchanged.
"""

from __future__ import annotations

import csv
import os
from typing import Any

HISTORY_FILENAME = "agent_state_history.csv"
HISTORY_FIELDS = ["agent_id", "step", "metric", "value"]


def history_path(output_dir: str) -> str:
    return os.path.join(output_dir, "state", HISTORY_FILENAME)


def _existing_steps(path: str) -> set[int]:
    """Steps already recorded on disk (resume-safety: never duplicate)."""
    steps: set[int] = set()
    if not os.path.exists(path):
        return steps
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    steps.add(int(row["step"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return steps
    return steps


class HistoryAppender:
    """Append-only writer of per-completed-day state-history rows.

    One instance per run. ``flush(state_history)`` writes every row whose
    step is not yet on disk, so calling it at the checkpoint boundary after
    each completed day — and once more at the end of the run — is idempotent
    and resume-safe.
    """

    def __init__(self, output_dir: str) -> None:
        self.path = history_path(output_dir)
        self._flushed: set[int] = _existing_steps(self.path)

    def flush(self, state_history: dict[Any, Any], *, step_offset: int = 0) -> int:
        """Append rows for not-yet-recorded steps. Returns rows written.

        ``step_offset`` shifts series indices to absolute sim-days, so a
        run resumed at day 4 records its first new series entry as step 4
        (and ``_flushed`` — initialized from the file it is appending to —
        keeps the resume duplication-free).
        """
        pending: dict[int, list[dict[str, Any]]] = {}
        for agent_id, series_by_metric in (state_history or {}).items():
            if not isinstance(series_by_metric, dict):
                continue
            for metric, series in series_by_metric.items():
                if not isinstance(series, (list, tuple)):
                    continue
                for idx, value in enumerate(series):
                    step = idx + step_offset
                    if step in self._flushed:
                        continue
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        continue
                    pending.setdefault(step, []).append(
                        {
                            "agent_id": agent_id,
                            "step": step,
                            "metric": metric,
                            "value": numeric,
                        }
                    )
        if not pending:
            return 0
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        new_file = not os.path.exists(self.path)
        written = 0
        with open(self.path, "a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
            if new_file:
                writer.writeheader()
            for step in sorted(pending):
                writer.writerows(pending[step])
                self._flushed.add(step)
                written += len(pending[step])
        return written


def copy_history(source_dir: str, target_dir: str) -> bool:
    """Carry a source run's completed-day history into a fresh output dir.

    Used when seeding a run from an earlier one: the fork continues the
    series instead of restarting it. The source file is only ever read.
    """
    import shutil

    src = history_path(source_dir)
    if not os.path.exists(src):
        return False
    dst = history_path(target_dir)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return True


__all__ = [
    "HISTORY_FIELDS",
    "HISTORY_FILENAME",
    "HistoryAppender",
    "copy_history",
    "history_path",
]
