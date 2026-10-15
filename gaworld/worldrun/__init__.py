"""``gaworld.worldrun`` — the shared GAWorld execution substrate.

Owns exactly five concerns (Phase 9 brief):

1. output isolation — the ONE authoritative reserved-key / path-key table
   (:mod:`gaworld.worldrun.config`);
2. checkpoint-restore launch semantics (:func:`seed_from_dir` delegates to
   :mod:`gaworld.checkpoints`; fresh output, source untouched, no
   destructive reset when seeded);
3. subprocess lifecycle primitives (:func:`launch_subprocess`, pause /
   resume consumed by the parallel-worlds adapter only);
4. the shared run manifest / status model
   (:mod:`gaworld.worldrun.manifest`, :mod:`gaworld.worldrun.lifecycle`);
5. completed-day state-history persistence
   (:mod:`gaworld.worldrun.history`).

Simulation runtime, agent/world state, checkpoint truth and the
intervention kernel stay owned by GAWorld itself; the parallel-worlds
runner keeps spec orchestration and analysis; SimTree keeps tree,
genealogy, interventions and recovery UX.
"""

from __future__ import annotations

from gaworld.worldrun.config import (
    RESERVED_CONFIG_KEYS,
    RESERVED_DOTTED_KEYS,
    ReservedOverrideError,
    run_root_overrides,
    validate_world_overrides,
)
from gaworld.worldrun.history import (
    HISTORY_FIELDS,
    HistoryAppender,
    copy_history,
    history_path,
)
from gaworld.worldrun.lifecycle import (
    STATUSES,
    TERMINAL_STATUSES,
    failure_status,
    is_terminal,
)
from gaworld.worldrun.manifest import (
    load_manifest,
    manifest_path,
    validate_manifest,
    write_manifest,
)
from gaworld.worldrun.run import (
    RunError,
    RunHandle,
    SubprocessHandle,
    WORLDRUN_VERSION,
    launch,
    launch_subprocess,
    seed_from_dir,
)

__all__ = [
    "HISTORY_FIELDS",
    "RESERVED_CONFIG_KEYS",
    "RESERVED_DOTTED_KEYS",
    "RESERVED_EXCLUDED",
    "RunError",
    "RunHandle",
    "STATUSES",
    "SubprocessHandle",
    "TERMINAL_STATUSES",
    "HistoryAppender",
    "ReservedOverrideError",
    "WORLDRUN_VERSION",
    "copy_history",
    "failure_status",
    "history_path",
    "is_terminal",
    "launch",
    "launch_subprocess",
    "load_manifest",
    "manifest_path",
    "run_root_overrides",
    "seed_from_dir",
    "validate_manifest",
    "validate_world_overrides",
    "write_manifest",
]
