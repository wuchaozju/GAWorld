"""Recorder — unified structured event recording (Agent-Kernel "Recorder").

Plugins may keep owning their bespoke output files (Database-per-Plugin);
the Recorder adds one shared, time-aligned event stream so cross-plugin
timelines, intervention audits and future replay don't require parsing five
different formats. One table == one JSONL file under ``base_dir``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import IO, TYPE_CHECKING

from gaworld.logging_setup import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from gaworld.kernel.clock import Clock

_LOG = get_logger("gaworld.kernel.recorder")

_TABLE_RE = re.compile(r"[^A-Za-z0-9._-]+")


class Recorder:
    """Append-only JSONL recorder with automatic clock stamping."""

    def __init__(self, base_dir: str = "output/records", clock: "Clock | None" = None):
        self.base_dir = Path(base_dir)
        self.clock = clock
        self._files: dict[str, IO[str]] = {}

    def record(self, table: str, data: dict) -> None:
        row = dict(data) if isinstance(data, dict) else {"value": data}
        if self.clock is not None:
            row.setdefault("_day", self.clock.day)
            row.setdefault("_time", self.clock.time_str)
        try:
            fh = self._file_for(table)
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
        except OSError as exc:
            _LOG.warning("recorder write to table %r failed: %s", table, exc)

    def _file_for(self, table: str) -> IO[str]:
        name = _TABLE_RE.sub("_", str(table)).strip("._") or "unnamed"
        fh = self._files.get(name)
        if fh is None:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            fh = open(self.base_dir / f"{name}.jsonl", "a", encoding="utf-8")
            self._files[name] = fh
        return fh

    def close(self) -> None:
        for fh in self._files.values():
            try:
                fh.close()
            except OSError:
                pass
        self._files = {}
