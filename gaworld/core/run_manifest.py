"""Structured run manifest for :func:`generative_city_sim.run_simulation`.

Why this exists
---------------
A simulation run today produces logs, memory files, plots, and CSVs
scattered under ``output/``. Six months later, nobody remembers:

* which git commit produced them,
* what ``sim_days`` / ``agent_ids`` / ``random_seed`` were in force,
* which LLM provider actually answered which task,
* what versions of ``pandas`` / ``numpy`` / ``networkx`` were installed,
* how many LLM calls the run made and how many failed.

The manifest is a single JSON file that captures all of that at the
end of every run. Paired with :mod:`gaworld.core.run_report`, it also
produces a single-file HTML report — no external CSS, no scripts to
load — that opens with a double-click.

Design principles
-----------------

* **Zero runtime dependencies beyond stdlib.** Everything the manifest
  captures is either introspectable at import time (``sys.version``,
  ``platform``), read from the environment (``git rev-parse``, output
  file listing), or handed in explicitly by the caller (config
  snapshot, LLM stats).
* **Cheap.** The end-of-run collection walks ``output/`` once and
  runs ``git rev-parse`` in a subprocess; anything that could take
  more than a second is opt-in.
* **Additive.** The module is imported and called from a single
  place in ``run_simulation``; disabling it is a one-line config
  change.
* **Redact-friendly.** Only the config keys we know to be non-secret
  are dumped verbatim; the rest are shape-summarised.

Public surface
--------------

* :func:`start_manifest` – called at the top of a run; returns the
  builder object.
* :class:`ManifestBuilder.finalise` – called at the end of a run;
  writes ``<manifest_dir>/<slug>.json`` and returns the path.
* :class:`ManifestBuilder.finalise_and_report` – also writes an HTML
  file next to the JSON.
* :func:`load_manifest` – helper for tests / tooling that reads a
  written manifest back.

Layout
------
A manifest is a plain dict with these top-level keys::

    {
      "schema_version": 1,
      "run_id":         "<uuid>",
      "slug":           "<yyyymmdd_hhmmss>",
      "started_at":     "<iso-8601>",
      "finished_at":    "<iso-8601>",
      "duration_s":     123.4,
      "outcome":        "ok" | "failed" | "in_progress",
      "environment":    {"python": "...", "platform": "...", "hostname": "..."},
      "git":            {"commit": "...", "branch": "...", "dirty": true},
      "dependencies":   {"pandas": "2.0.3", ...},
      "config":         {...},   # curated subset
      "run":            {"sim_days": 30, "agent_ids": [...], "random_seed": 42},
      "llm":            {"call_count": 512, "by_task": {...}, "by_provider": {...},
                          "failure_count": 3},
      "artefacts":      {"logs": [...], "memory": [...], "state": [...]}
    }
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.run_manifest")

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------
# Curated config keys. Everything not on this list is shape-summarised.
# ---------------------------------------------------------------------

_CONFIG_KEYS_VERBATIM: tuple[str, ...] = (
    "agent_ids",
    "sim_days",
    "seconds_per_day",
    "simulate_realtime",
    "time_step_minutes",
    "stateful",
    "background",
    "memory_model_version",
    "require_clean_reset_on_memory_model_change",
    "csv_path",
    "md_path",
    "map_path",
    "memory_dir",
    "log_dir",
    "diary_output_dir",
    "environment_output_dir",
    "random_seed",
)

# Config sub-blocks summarised as {"enabled": bool} + a few knobs.
_CONFIG_ENABLE_BLOCKS: tuple[str, ...] = (
    "news",
    "external_rag",
    "intervention",
    "external_environment_service",
    "distributed",
    "visualization",
    "life_events",
    "human_realism",
    "concurrency",
    "economy",
    "run_manifest",
)


# ---------------------------------------------------------------------
# Small helpers (pure functions to make them testable in isolation)
# ---------------------------------------------------------------------

def _iso_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _slug_from(ts: str) -> str:
    # ISO like 2026-04-25T12:34:56+00:00 → 20260425_123456
    core = ts.split("+", 1)[0].split(".", 1)[0]
    return core.replace("-", "").replace(":", "").replace("T", "_")


def _safe_str(value: Any, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _git_info(repo_root: str) -> dict[str, Any]:
    """Return {commit, branch, dirty} or an empty dict on failure."""
    def _run(args: list[str]) -> str:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout.strip() if proc.returncode == 0 else ""

    commit = _run(["rev-parse", "HEAD"])
    if not commit:
        return {}
    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    status = _run(["status", "--porcelain"])
    return {
        "commit": commit,
        "branch": branch or "",
        "dirty": bool(status),
    }


def _dependency_versions(names: Iterable[str]) -> dict[str, str]:
    """Return best-effort ``{package: version}``.

    Uses :mod:`importlib.metadata` so we don't need to import the
    package (which for e.g. ``matplotlib`` would drag Qt sniffing in
    and slow the run down).
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover — stdlib on all supported versions
        return {}
    out: dict[str, str] = {}
    for name in names:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "not-installed"
        except Exception as exc:  # noqa: BLE001 — metadata is best-effort
            out[name] = f"error:{exc.__class__.__name__}"
    return out


def _environment_snapshot() -> dict[str, Any]:
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    return {
        "python": sys.version.split()[0],
        "python_impl": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hostname": hostname,
        "pid": os.getpid(),
    }


def _curate_config(cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    """Summarise ``cfg`` — verbatim for known scalars, shape for the rest."""
    if not isinstance(cfg, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in _CONFIG_KEYS_VERBATIM:
        if key in cfg:
            out[key] = cfg[key]
    for key in _CONFIG_ENABLE_BLOCKS:
        block = cfg.get(key)
        if isinstance(block, Mapping):
            summary: dict[str, Any] = {"enabled": bool(block.get("enabled", True))}
            # Pull a few widely-used knobs verbatim if present.
            for knob in ("workers", "day_routine_workers", "top_k", "state_path"):
                if knob in block:
                    summary[knob] = block[knob]
            out[key] = summary
    # LLM routing shape without the API keys.
    llm = cfg.get("llm")
    if isinstance(llm, Mapping):
        providers = llm.get("providers", {}) or {}
        routing = llm.get("routing", {}) or {}
        redacted_providers: dict[str, Any] = {}
        if isinstance(providers, Mapping):
            for name, entry in providers.items():
                if not isinstance(entry, Mapping):
                    continue
                redacted_providers[name] = {
                    "type": entry.get("type", ""),
                    "model": entry.get("model", ""),
                    "base_url": entry.get("base_url") or entry.get("url") or "",
                }
        out["llm"] = {
            "providers": redacted_providers,
            "routing": {
                "default": routing.get("default", ""),
                "fallback": routing.get("fallback", []),
                "tasks": routing.get("tasks", {}),
            },
        }
    return out


def _list_artefacts(root: str, subdirs: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """Return ``{subdir: [{path, size, mtime}]}`` for files under ``root/<subdir>``.

    Silently skips missing directories and unreadable files.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for sub in subdirs:
        entries: list[dict[str, Any]] = []
        path = os.path.join(root, sub) if not os.path.isabs(sub) else sub
        if not os.path.isdir(path):
            out[sub] = entries
            continue
        for dirpath, _dirs, files in os.walk(path):
            for name in files:
                fp = os.path.join(dirpath, name)
                try:
                    stat = os.stat(fp)
                except OSError:
                    continue
                rel = os.path.relpath(fp, root)
                entries.append(
                    {
                        "path": rel,
                        "size": int(stat.st_size),
                        "mtime": int(stat.st_mtime),
                    }
                )
        # Deterministic ordering makes diffs across runs actually
        # informative.
        entries.sort(key=lambda e: e["path"])
        out[sub] = entries
    return out


# ---------------------------------------------------------------------
# ManifestBuilder
# ---------------------------------------------------------------------

@dataclass
class ManifestBuilder:
    """Collect a run manifest and persist it as JSON (+ optional HTML)."""

    repo_root: str
    manifest_dir: str
    config: Mapping[str, Any] = field(default_factory=dict)
    dependency_names: tuple[str, ...] = (
        "pandas", "numpy", "requests", "matplotlib", "networkx",
    )
    partial_write: bool = True
    _run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _started_iso: str = field(default_factory=_iso_now)
    _started_perf: float = field(default_factory=time.perf_counter)
    _slug: str = field(init=False)
    _notes: list[str] = field(default_factory=list)
    _events: list[dict[str, Any]] = field(default_factory=list)
    _llm_stats_provider: Any = None

    def __post_init__(self) -> None:
        self._slug = _slug_from(self._started_iso)

    # ---------- observation helpers ---------------------------------

    def bind_llm_stats(self, provider: Any) -> None:
        """Attach an object exposing ``snapshot() -> dict``.

        Used to fold LLM call counters into the manifest at end-of-run
        without hard-wiring an import cycle.
        """
        self._llm_stats_provider = provider

    def note(self, text: str) -> None:
        self._notes.append(_safe_str(text))

    def event(self, kind: str, **payload: Any) -> None:
        """Record a lightweight timestamped event (e.g. day boundaries)."""
        self._events.append(
            {"ts": _iso_now(), "kind": str(kind), "payload": payload}
        )

    # ---------- persistence ----------------------------------------

    @property
    def slug(self) -> str:
        return self._slug

    def manifest_path(self, ext: str = ".json") -> str:
        return os.path.join(self.manifest_dir, f"{self._slug}{ext}")

    def build(
        self,
        outcome: str = "in_progress",
        error: str | None = None,
    ) -> dict[str, Any]:
        finished_iso = _iso_now() if outcome != "in_progress" else ""
        duration = round(time.perf_counter() - self._started_perf, 3)
        llm_snapshot: dict[str, Any] = {}
        if self._llm_stats_provider is not None:
            try:
                llm_snapshot = self._llm_stats_provider.snapshot()
            except Exception as exc:  # noqa: BLE001 — snapshot must never crash finalisation
                _LOG.warning("LLM stats snapshot failed: %s", exc)
                llm_snapshot = {"error": _safe_str(exc)}

        artefacts_root = str(self.config.get("output_root") or _default_output_root(self.config))
        artefact_subs: tuple[str, ...] = (
            self.config.get("log_dir", "output/logs"),
            self.config.get("memory_dir", "output/memory"),
            self.config.get("diary_output_dir", "output/diaries"),
            self.config.get("environment_output_dir", "output/environment"),
            "output/state",
        )

        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self._run_id,
            "slug": self._slug,
            "started_at": self._started_iso,
            "finished_at": finished_iso,
            "duration_s": duration,
            "outcome": outcome,
            "error": error or "",
            "environment": _environment_snapshot(),
            "git": _git_info(self.repo_root),
            "dependencies": _dependency_versions(self.dependency_names),
            "config": _curate_config(self.config),
            "run": {
                "sim_days": self.config.get("sim_days"),
                "agent_ids": list(self.config.get("agent_ids", []) or []),
                "random_seed": self.config.get("random_seed"),
                "stateful": bool(self.config.get("stateful", False)),
            },
            "llm": llm_snapshot,
            "artefacts": _list_artefacts(self.repo_root, artefact_subs) if outcome != "in_progress" else {},
            "notes": list(self._notes),
            "events": list(self._events),
        }
        return manifest

    def finalise(
        self,
        outcome: str = "ok",
        error: str | None = None,
    ) -> str:
        """Write the final manifest JSON. Returns the file path."""
        os.makedirs(self.manifest_dir, exist_ok=True)
        manifest = self.build(outcome=outcome, error=error)
        target = self.manifest_path(".json")
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=False)
        os.replace(tmp, target)
        # Drop the run-start breadcrumb; the final file supersedes it.
        # Failed / crashed runs still keep their .partial.json because
        # they never reach finalise().
        partial = os.path.join(self.manifest_dir, f"{self._slug}.partial.json")
        try:
            if os.path.exists(partial):
                os.remove(partial)
        except OSError:
            # Not worth escalating — the file is a debugging aid.
            pass
        _LOG.info("run_manifest written path=%s outcome=%s", target, outcome)
        return target

    def finalise_and_report(
        self,
        outcome: str = "ok",
        error: str | None = None,
    ) -> tuple[str, str]:
        """Write JSON + HTML report. Returns ``(json_path, html_path)``."""
        json_path = self.finalise(outcome=outcome, error=error)
        # Deferred import to avoid a hard cycle at module load time.
        from gaworld.core.run_report import render_report

        with open(json_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        html_path = self.manifest_path(".html")
        html = render_report(manifest)
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        _LOG.info("run_report written path=%s", html_path)
        return json_path, html_path

    def write_partial(self) -> str | None:
        """Snapshot the current state (outcome='in_progress').

        Handy when a run crashes: at least the last partial manifest
        survives.
        """
        if not self.partial_write:
            return None
        try:
            os.makedirs(self.manifest_dir, exist_ok=True)
            manifest = self.build(outcome="in_progress")
            target = os.path.join(self.manifest_dir, f"{self._slug}.partial.json")
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
            return target
        except OSError as exc:
            _LOG.warning("partial run_manifest write failed: %s", exc)
            return None


def _default_output_root(cfg: Mapping[str, Any] | None) -> str:
    if isinstance(cfg, Mapping):
        for key in ("output_root", "log_dir"):
            value = cfg.get(key)
            if isinstance(value, str) and value:
                # e.g. output/logs → output
                head, _tail = os.path.split(value.rstrip("/"))
                return head or "output"
    return "output"


def start_manifest(
    *,
    config: Mapping[str, Any],
    repo_root: str | None = None,
    manifest_dir: str | None = None,
) -> ManifestBuilder:
    """Instantiate a :class:`ManifestBuilder` with sensible defaults.

    Called once at the top of ``run_simulation``. The returned builder
    is passed to :func:`finalise_from_hook` at the end of the run (or
    from the ``on_simulation_end`` hook), so the intermediate state
    doesn't need to be threaded through every call in between.
    """
    repo = repo_root or os.getcwd()
    block = config.get("run_manifest", {}) if isinstance(config, Mapping) else {}
    if not isinstance(block, Mapping):
        block = {}
    target = manifest_dir or block.get("output_dir") or os.path.join("output", "run_manifests")
    builder = ManifestBuilder(
        repo_root=repo,
        manifest_dir=str(target),
        config=dict(config) if isinstance(config, Mapping) else {},
        partial_write=bool(block.get("partial_write", True)),
    )
    builder.write_partial()
    return builder


def load_manifest(path: str) -> dict[str, Any]:
    """Read a manifest JSON back into a dict.

    Missing / malformed files raise so tests can rely on hard failures
    instead of quiet ``{}``.
    """
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


__all__ = [
    "ManifestBuilder",
    "SCHEMA_VERSION",
    "load_manifest",
    "start_manifest",
]
