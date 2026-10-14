"""Durable day-boundary checkpoints for GAWorld simulations (Phase 5).

SAVE / RESTORE / CONTINUE only — no retry, no rollback, no branching
(PHASE5-BRIEF scope guards).  Checkpoints are runtime truth: outputs
(CSV/timeline/reports/plots) are never checkpoint state.  No secrets are
ever serialized.

Layout (run-relative)::

    <run_dir>/checkpoints/day_0000/{manifest.json, state.json, ...}
    <run_dir>/checkpoints/day_0001/...

Writes are atomic: a temp directory is filled, validated, then renamed
into ``day_NNNN``; discovery never lists partial/temp directories and a
valid checkpoint is never silently overwritten.

Components are captured through a serialization-hook registry: the kernel,
plugins and launcher register hooks instead of the manager hardcoding a
component list.  Built-in hooks cover the shapes shared by every runtime
(day cursor, agent ids/agents, runtime config, LLM routing provenance,
Python ``random`` and NumPy generators).
"""

from __future__ import annotations

import base64
import json
import os
import pickle
import random
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

CHECKPOINT_VERSION = 1
CHECKPOINT_DIRNAME = "checkpoints"
MANIFEST_NAME = "manifest.json"
STATE_NAME = "state.json"
STATE_PICKLE_NAME = "state.pkl"
_TMP_PREFIX = ".tmp-"
_DAY_RE = re.compile(r"^day_(\d{4})$")

# Keys whose values must never reach the disk (brief §4/§10: identifiers OK,
# credentials never).  Matched case-insensitively against dict keys.
_SECRET_KEY_RE = re.compile(
    r"api_key|apikey|secret|token|password|passwd|credential|jwt|authorization",
    re.IGNORECASE,
)


class CheckpointError(Exception):
    """Base class for all checkpoint failures (precise, human-readable)."""


class CheckpointExists(CheckpointError):
    """A valid checkpoint for this day already exists (no silent overwrite)."""


class CheckpointNotFound(CheckpointError):
    """No checkpoint matches the requested reference."""


class CheckpointVersionUnsupported(CheckpointError):
    """The checkpoint was written by an incompatible checkpoint_version."""


class CheckpointCorrupted(CheckpointError):
    """Manifest or state payload is missing/invalid; nothing was restored."""


@dataclass(frozen=True)
class CheckpointRef:
    """Stable reference: run_id + day.  String form ``<run_id>:day_NNNN``."""

    run_id: str
    completed_day: int
    path: str = ""

    def as_str(self) -> str:
        return f"{self.run_id}:day_{self.completed_day:04d}"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.as_str()


def sanitize_config(config: Any) -> Any:
    """Deep-copy a config-like structure with secret values redacted."""
    if isinstance(config, dict):
        return {
            k: ("[REDACTED]" if _SECRET_KEY_RE.search(str(k)) else sanitize_config(v))
            for k, v in config.items()
        }
    if isinstance(config, (list, tuple)):
        return [sanitize_config(v) for v in config]
    if isinstance(config, (str, int, float, bool)) or config is None:
        return config
    return repr(config)  # non-JSON-safe objects become identifiers only


class CheckpointManager:
    """GAWorld-owned checkpoint orchestration (brief §2, §3, §7, §13)."""

    def __init__(
        self,
        run_dir: os.PathLike | str,
        run_id: str,
        hooks: dict[str, dict[str, Callable]] | None = None,
    ) -> None:
        # default to the built-in hook set covering common runtime shapes
        if hooks is None:
            hooks = DEFAULT_HOOKS
        self.run_dir = Path(run_dir)
        self.run_id = str(run_id)
        self.checkpoints_dir = self.run_dir / CHECKPOINT_DIRNAME
        # Component serialization-hook registry: name -> {"save": fn, "load": fn}
        # save(runtime) -> JSON-safe payload; load(runtime, payload) -> None
        self._hooks: dict[str, dict[str, Callable]] = {}
        for name, pair in (hooks or {}).items():
            self.register_hook(name, **pair)

    # ------------------------------------------------------------------
    # Hook registry (brief §2: components expose serialization hooks)
    # ------------------------------------------------------------------
    def register_hook(self, name: str, save: Callable, load: Callable) -> None:
        self._hooks[name] = {"save": save, "load": load}

    def hook_names(self) -> list[str]:
        return sorted(self._hooks)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save_checkpoint(
        self,
        runtime: Any,
        completed_day: int,
        overwrite: bool = False,
        extra_manifest: dict | None = None,
    ) -> CheckpointRef:
        completed_day = int(completed_day)
        day_dir = self.checkpoints_dir / f"day_{completed_day:04d}"
        if day_dir.exists() and not overwrite:
            raise CheckpointExists(
                f"refusing to overwrite valid checkpoint {day_dir} — "
                "pass overwrite=True only if you know the existing checkpoint is bad"
            )
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        state = self._collect_state(runtime)
        # the explicitly requested day is authoritative over the runtime attr
        state["completed_day"] = completed_day
        manifest = self._build_manifest(runtime, completed_day, state, extra_manifest)

        tmp_dir = self.checkpoints_dir / f"{_TMP_PREFIX}day_{completed_day:04d}"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True)
        try:
            state_name, state_format = self._write_state(tmp_dir, state)
            # validate contents before the manifest is laid down (brief §7)
            if self._read_state(tmp_dir / state_name, state_format) != state:
                raise CheckpointCorrupted("state payload failed round-trip validation")
            manifest["state_files"] = [state_name]
            manifest["state_format"] = state_format
            (tmp_dir / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str),
                "utf-8",
            )
            if day_dir.exists():
                shutil.rmtree(day_dir)
            os.replace(tmp_dir, day_dir)  # atomic rename into place
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        return CheckpointRef(
            run_id=self.run_id, completed_day=completed_day, path=str(day_dir)
        )

    def _collect_state(self, runtime: Any) -> dict:
        state: dict[str, Any] = {}
        for name, pair in sorted(self._hooks.items()):
            try:
                payload = pair["save"](runtime)
            except _HookNotApplicable:
                continue
            state[name] = payload
        if not state:
            raise CheckpointError(
                "no serialization hooks registered — nothing to checkpoint"
            )
        return state

    def _write_state(self, dir_path: Path, state: dict) -> tuple[str, str]:
        """Write state as JSON when possible, else pickle (heavy graphs,
        tuples, numpy dtypes).  Returns (filename, format)."""
        try:
            blob = json.dumps(state, ensure_ascii=False, sort_keys=True)
            (dir_path / STATE_NAME).write_text(blob, "utf-8")
            return STATE_NAME, "json"
        except (TypeError, ValueError):
            blob = pickle.dumps(state, protocol=4)
            (dir_path / STATE_PICKLE_NAME).write_bytes(blob)
            return STATE_PICKLE_NAME, "pickle"

    @staticmethod
    def _read_state(path: Path, state_format: str) -> Any:
        if state_format == "pickle" or path.suffix == ".pkl":
            try:
                return pickle.loads(path.read_bytes())
            except Exception as exc:
                raise CheckpointCorrupted(
                    f"checkpoint state file {path} is corrupted (unpicklable): {exc}"
                ) from exc
        try:
            return json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise CheckpointCorrupted(
                f"checkpoint state file {path} is corrupted (not valid JSON): {exc}"
            ) from exc

    def _build_manifest(
        self, runtime: Any, completed_day: int, state: dict, extra: dict | None
    ) -> dict:
        config_snapshot = {}
        if "config" in state:
            config_snapshot = state["config"]
        manifest = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "run_id": self.run_id,
            "completed_day": completed_day,
            "city": (config_snapshot or {}).get("city", "") if isinstance(config_snapshot, dict) else "",
            "agent_ids": state.get("agent_ids", []),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state_files": [STATE_NAME],
            "state_format": "json",
            "state": state,  # small runtimes inline; file copy kept for layout stability
            "sim_config_snapshot": sanitize_config(config_snapshot),
            "routing_provenance": sanitize_config(state.get("routing", {})),
            "llm_routing": sanitize_config(state.get("routing", {})),
        }
        if extra:
            manifest.update(sanitize_config(extra))
        return manifest

    # ------------------------------------------------------------------
    # Discovery (never lists partial/temp writes — brief §7, §13)
    # ------------------------------------------------------------------
    def _known_days(self) -> list[int]:
        if not self.checkpoints_dir.is_dir():
            return []
        days = []
        for entry in self.checkpoints_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith(_TMP_PREFIX):
                continue
            m = _DAY_RE.match(entry.name)
            if not m:
                continue
            manifest_path = entry / MANIFEST_NAME
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text("utf-8"))
                day = int(manifest["completed_day"])
            except Exception:  # unreadable manifest → not a valid checkpoint
                continue
            if any(
                not (entry / rel).is_file() for rel in manifest.get("state_files", [])
            ):
                continue
            if day != int(m.group(1)):
                continue
            days.append(day)
        return sorted(days)

    def list_checkpoints(self) -> list[CheckpointRef]:
        return [
            CheckpointRef(
                run_id=self.run_id,
                completed_day=day,
                path=str(self.checkpoints_dir / f"day_{day:04d}"),
            )
            for day in self._known_days()
        ]

    def latest_checkpoint(self) -> CheckpointRef | None:
        days = self._known_days()
        if not days:
            return None
        day = days[-1]
        return CheckpointRef(
            run_id=self.run_id,
            completed_day=day,
            path=str(self.checkpoints_dir / f"day_{day:04d}"),
        )

    def resolve_ref(self, ref: str) -> CheckpointRef:
        """Resolve a launcher-facing ``<run_id>:day_NNNN`` reference."""
        text = str(ref).strip()
        m = re.match(r"^(?P<run>[^:]+):day_(?P<day>\d+)$", text)
        if not m:
            raise CheckpointNotFound(
                f"invalid checkpoint reference {ref!r} — expected '<run_id>:day_NNNN'"
            )
        day = int(m.group("day"))
        if m.group("run") != self.run_id:
            raise CheckpointNotFound(
                f"checkpoint reference {ref!r} belongs to run {m.group('run')!r}, "
                f"not this run ({self.run_id!r})"
            )
        return CheckpointRef(
            run_id=self.run_id,
            completed_day=day,
            path=str(self.checkpoints_dir / f"day_{day:04d}"),
        )

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------
    def restore_checkpoint(
        self,
        runtime: Any,
        ref: CheckpointRef | str | None = None,
        completed_day: int | None = None,
        config_overrides: dict | None = None,
    ) -> CheckpointRef:
        """Restore a checkpoint into ``runtime``.

        Validation happens fully BEFORE any runtime field is touched: an
        unsupported version or corrupted payload leaves the runtime
        untouched (no partial continuation — brief §9).
        """
        target = self._locate(ref, completed_day)
        day_dir = Path(target.path)
        manifest_path = day_dir / MANIFEST_NAME
        if not manifest_path.is_file():
            raise CheckpointNotFound(f"no manifest at {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise CheckpointCorrupted(
                f"checkpoint manifest at {manifest_path} is not valid JSON: {exc}"
            ) from exc

        version = manifest.get("checkpoint_version")
        if version != CHECKPOINT_VERSION:
            raise CheckpointVersionUnsupported(
                f"checkpoint_version={version!r} at {manifest_path} is unsupported "
                f"(this runtime supports checkpoint_version={CHECKPOINT_VERSION})"
            )
        if target.completed_day < 0:
            try:
                target = CheckpointRef(
                    run_id=target.run_id,
                    completed_day=int(manifest["completed_day"]),
                    path=target.path,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CheckpointCorrupted(
                    f"manifest at {manifest_path} has no valid completed_day"
                ) from exc

        state_path = day_dir / (manifest.get("state_files") or [STATE_NAME])[0]
        state = self._read_state(state_path, manifest.get("state_format", "json"))
        if not isinstance(state, dict):
            raise CheckpointCorrupted(
                f"checkpoint state at {state_path} must be a JSON object"
            )

        # All validation passed — apply state, then config overrides (brief §8/§14:
        # runtime-config overrides stay distinguishable from simulation state).
        for name, payload in sorted(state.items()):
            pair = self._hooks.get(name)
            if pair is None:
                raise CheckpointCorrupted(
                    f"checkpoint component {name!r} has no registered "
                    "serialization hook — refusing partial restore"
                )
            pair["load"](runtime, payload)
        if config_overrides:
            cfg = getattr(runtime, "config", None)
            if isinstance(cfg, dict):
                cfg.update(config_overrides)
        return target

    def _locate(
        self, ref: CheckpointRef | str | None, completed_day: int | None
    ) -> CheckpointRef:
        if ref is not None:
            if isinstance(ref, CheckpointRef):
                if ref.run_id != self.run_id:
                    raise CheckpointNotFound(
                        f"checkpoint ref {ref.as_str()!r} belongs to run "
                        f"{ref.run_id!r}, not {self.run_id!r}"
                    )
                target = ref
            elif isinstance(ref, (str, os.PathLike)) and (
                str(ref).endswith(".json") or "/" in str(ref) or os.sep in str(ref)
            ):
                # filesystem form: a checkpoint day directory (or its manifest)
                path = Path(ref)
                if path.name == MANIFEST_NAME:
                    path = path.parent
                target = CheckpointRef(
                    run_id=self.run_id, completed_day=-1, path=str(path)
                )
            else:
                target = self.resolve_ref(ref)
        elif completed_day is not None:
            target = CheckpointRef(
                run_id=self.run_id,
                completed_day=int(completed_day),
                path=str(self.checkpoints_dir / f"day_{int(completed_day):04d}"),
            )
        else:
            latest = self.latest_checkpoint()
            if latest is None:
                raise CheckpointNotFound(
                    f"no checkpoints found under {self.checkpoints_dir}"
                )
            target = latest
        if not (Path(target.path) / MANIFEST_NAME).is_file():
            raise CheckpointNotFound(
                f"checkpoint day_{target.completed_day:04d} not found or "
                f"incomplete under {self.checkpoints_dir}"
            )
        return target


# ----------------------------------------------------------------------
# Built-in serialization hooks (shared shapes across runtimes)
# ----------------------------------------------------------------------
class _HookNotApplicable(Exception):
    """Raised by a save hook when the runtime lacks the component."""


def _encode(obj: Any) -> Any:
    """JSON-safe encode that preserves non-string dict keys (e.g. int agent ids)."""
    if isinstance(obj, dict) and any(not isinstance(k, str) for k in obj):
        return {
            "__ga_dict__": [[_encode(k), _encode(v)] for k, v in obj.items()]
        }
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    return obj


def _decode(obj: Any) -> Any:
    if isinstance(obj, dict) and "__ga_dict__" in obj and len(obj) == 1:
        return {_decode(k): _decode(v) for k, v in obj["__ga_dict__"]}
    if isinstance(obj, dict):
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


def _attr(name: str) -> Callable:
    def save(runtime: Any) -> Any:
        if not hasattr(runtime, name):
            raise _HookNotApplicable(name)
        return _encode(getattr(runtime, name))

    def load(runtime: Any, payload: Any) -> None:
        setattr(runtime, name, _decode(payload))

    return save, load


def _rng_python_save(runtime: Any) -> Any:
    rng = getattr(runtime, "rng_python", None)
    if rng is None:
        raise _HookNotApplicable("rng_python")
    return json.loads(json.dumps(rng.getstate()))


def _rng_python_load(runtime: Any, payload: Any) -> None:
    # JSON turns the internalstate tuple into a list — restore it as a tuple
    if isinstance(payload, (list, tuple)) and len(payload) == 3 and isinstance(
        payload[1], list
    ):
        payload = [payload[0], tuple(payload[1]), payload[2]]
    runtime.rng_python.setstate(tuple(payload))


def _rng_numpy_save(runtime: Any) -> Any:
    rng = getattr(runtime, "rng_numpy", None)
    if rng is None:
        raise _HookNotApplicable("rng_numpy")
    return json.loads(json.dumps(rng.bit_generator.state))


def _rng_numpy_load(runtime: Any, payload: Any) -> None:
    gen = getattr(runtime, "rng_numpy", None)
    if not isinstance(gen, np.random.Generator):
        gen = np.random.default_rng(0)
        runtime.rng_numpy = gen
    gen.bit_generator.state = payload


def default_hooks() -> dict[str, dict[str, Callable]]:
    """Built-in hook set covering the common runtime shapes."""
    hooks: dict[str, dict[str, Callable]] = {}
    for attr in ("completed_day", "agent_ids", "agents", "routing"):
        save, load = _attr(attr)
        hooks[attr] = {"save": save, "load": load}

    def config_save(runtime: Any) -> Any:
        cfg = getattr(runtime, "config", None)
        if cfg is None:
            raise _HookNotApplicable("config")
        return _encode(sanitize_config(cfg))

    hooks["config"] = {"save": config_save, "load": _attr("config")[1]}
    hooks["rng_python"] = {"save": _rng_python_save, "load": _rng_python_load}
    hooks["rng_numpy"] = {"save": _rng_numpy_save, "load": _rng_numpy_load}
    return hooks


DEFAULT_HOOKS = default_hooks()


# ----------------------------------------------------------------------
# Real-simulation hooks (generative_city_sim.run_simulation runtime)
# ----------------------------------------------------------------------
# Components live in a plain dict ("checkpoint carrier") so the launcher
# stays in charge of where each component comes from and goes; the hooks
# only know how to (de)serialize.  Heavy object graphs (agent dicts with
# numpy values, plugin_state namespaces) use pickle — GAWorld-internal
# runtime objects in a local, trusted run directory; handles/sockets/
# threads are NEVER put into the carrier (brief §10: reconstruct on
# restore instead — a pickled handle fails loudly, never silently).
# Secrets never enter the carrier: the config snapshot is sanitized and
# the launcher only passes state components, never credentials.

def _rng_capture() -> dict:
    """Snapshot the global RNG surfaces (python random + legacy numpy)."""
    np_state = np.random.get_state()
    return {
        "python": json.loads(json.dumps(random.getstate())),
        "numpy_global": {
            "strategy": np_state[0],
            "keys": np.asarray(np_state[1]).tolist(),
            "pos": int(np_state[2]),
            "has_gauss": int(np_state[3]),
            "cached_gauss": np_state[4],
        },
    }


def _rng_apply(payload: dict) -> None:
    random.setstate(_rng_python_tuple(payload["python"]))
    ng = payload["numpy_global"]
    np.random.set_state(
        (
            ng["strategy"],
            np.asarray(ng["keys"], dtype=np.uint32),
            int(ng["pos"]),
            int(ng["has_gauss"]),
            float(ng.get("cached_gauss", -1.0)),
        )
    )


def _rng_python_tuple(payload: Any) -> tuple:
    if isinstance(payload, (list, tuple)) and len(payload) == 3 and isinstance(
        payload[1], list
    ):
        return (payload[0], tuple(payload[1]), payload[2])
    return tuple(payload)  # type: ignore[return-value]


def simulation_state_hooks() -> dict[str, dict[str, Callable]]:
    """Hook set for the real launcher runtime (carrier-dict based)."""

    def pickle_component(key: str):
        def save(rt: dict) -> bytes:
            if key not in rt or rt[key] is None:
                raise _HookNotApplicable(key)
            return pickle.dumps(rt[key], protocol=4)

        def load(rt: dict, payload: bytes) -> None:
            rt[key] = pickle.loads(payload)

        return save, load

    def json_component(key: str, transform=None):
        def save(rt: dict) -> Any:
            if key not in rt or rt[key] is None:
                raise _HookNotApplicable(key)
            value = rt[key]
            return transform(value, "save") if transform else _encode(value)

        def load(rt: dict, payload: Any) -> None:
            rt[key] = transform(payload, "load") if transform else _decode(payload)

        return save, load

    hooks: dict[str, dict[str, Callable]] = {
        "completed_day": dict(
            zip(("save", "load"), json_component("completed_day"))
        ),
        "agents": dict(zip(("save", "load"), pickle_component("agents"))),
        "plugin_state": dict(zip(("save", "load"), pickle_component("plugin_state"))),
        "extension_state": dict(
            zip(("save", "load"), pickle_component("extension_state"))
        ),
        "clock": dict(zip(("save", "load"), json_component("clock"))),
        "agent_day_cursor": dict(
            zip(("save", "load"), json_component("agent_day_cursor"))
        ),
        "env_runtime": dict(zip(("save", "load"), json_component("env_runtime"))),
    }
    hooks["rng"] = {
        "save": lambda rt: _rng_capture(),
        "load": lambda rt, payload: _rng_apply(payload),
    }
    return hooks
