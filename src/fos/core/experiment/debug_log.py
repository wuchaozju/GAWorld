"""
Shared debug logging for experiment execution.

Provides a single debug file that both runner and controller write to,
making it easy to follow the full prompt/response flow. Includes
scenario start/end markers so multiple scenarios in the same file
are easy to distinguish.

Contains: get_debug_file, write_debug, reset_debug_file, write_scenario_header
"""

from pathlib import Path
from datetime import datetime
from typing import List
import os
import threading

from fos.core.runtime_paths import get_runtime_debug_dir

# Shared debug file path - created once per session
_debug_dir = get_runtime_debug_dir()

# Use a lock for thread-safe writes
_write_lock = threading.Lock()

# Gate debug logging behind FOS_DEBUG env var
_DEBUG_ENABLED = os.getenv("FOS_DEBUG", "").lower() in ("true", "1", "yes")

# Global debug file for this session
_session_debug_file: Path | None = None


def get_debug_file() -> Path:
    """Get the shared debug file for this session.

    Creates a new file on first call, then returns the same file
    for all subsequent calls in this session.

    Returns:
        Path to the debug file
    """
    global _session_debug_file

    with _write_lock:
        if _session_debug_file is None:
            _session_debug_file = _debug_dir / f"experiment_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            # Write header
            with open(_session_debug_file, 'w', encoding='utf-8') as f:
                f.write(f"Experiment Debug Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

        return _session_debug_file


def write_debug(content: str) -> None:
    """Write content to the shared debug file.

    Args:
        content: Text to write to the debug file
    """
    # Allow writes when _session_debug_file is explicitly set (e.g. test override)
    # even if FOS_DEBUG is not enabled.
    if not _DEBUG_ENABLED and _session_debug_file is None:
        return
    debug_file = get_debug_file()
    with _write_lock:
        with open(debug_file, 'a', encoding='utf-8') as f:
            f.write(content)


def write_scenario_header(
    scenario_id: str,
    agent_names: List[str],
    params: dict | None = None,
) -> None:
    """Write a scenario start marker to the shared debug file.

    Call this when a new scenario begins running so that multiple
    scenarios in the same file are easy to distinguish.

    Args:
        scenario_id: The scenario identifier (e.g. "council_chamber")
        agent_names: List of agent names in this scenario
        params: Optional scenario parameters for context
    """
    if not _DEBUG_ENABLED and _session_debug_file is None:
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sep = "=" * 80
    lines = [
        f"\n{sep}\n",
        f"# SCENARIO START: {scenario_id}  [{now}]\n",
        f"# Agents: {', '.join(agent_names)}\n",
    ]
    if params:
        for k, v in params.items():
            lines.append(f"# Param: {k} = {v}\n")
    lines.append(f"{sep}\n\n")
    write_debug("".join(lines))


def write_scenario_footer(scenario_id: str) -> None:
    """Write a scenario end marker to the shared debug file.

    Args:
        scenario_id: The scenario identifier that just finished
    """
    if not _DEBUG_ENABLED and _session_debug_file is None:
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sep = "=" * 80
    write_debug(f"\n{sep}\n# SCENARIO END: {scenario_id}  [{now}]\n{sep}\n\n")


def reset_debug_file() -> Path:
    """Reset the debug file for a new session.

    Useful for testing or when starting a new experiment run.

    Returns:
        Path to the new debug file
    """
    global _session_debug_file
    _session_debug_file = None
    return get_debug_file()
