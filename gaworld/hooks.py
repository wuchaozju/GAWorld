"""Lifecycle hook dispatcher (HookBus).

Canonical home: :mod:`gaworld.hooks`.
Legacy callers should use the ``extensibility`` shim at the project root.
"""

from __future__ import annotations

import importlib
from collections import defaultdict

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.hooks")


class HookBus:
    """Simple lifecycle hook dispatcher loaded from CONFIG."""

    def __init__(self, config=None):
        cfg = config or {}
        self.strict = bool(cfg.get("strict", False))
        self._hooks = defaultdict(list)
        hook_map = cfg.get("hooks", {})
        if isinstance(hook_map, dict):
            for phase, paths in hook_map.items():
                if isinstance(paths, str):
                    paths = [paths]
                if not isinstance(paths, list):
                    continue
                for path in paths:
                    fn = self._load_callable(path)
                    if fn:
                        self.register(phase, fn)

    def register(self, phase, fn):
        if not callable(fn):
            return
        self._hooks[str(phase)].append(fn)

    def emit(self, phase, **context):
        errors = []
        for fn in self._hooks.get(str(phase), []):
            try:
                fn(context)
            except Exception as exc:  # pragma: no cover - best effort extension safety
                # User extensions can raise anything; treat the bus as a trust boundary.
                _LOG.warning(
                    "hook %s.%s in phase %s raised: %s",
                    fn.__module__,
                    fn.__name__,
                    phase,
                    exc,
                )
                errors.append(f"{fn.__module__}.{fn.__name__}: {exc}")
        if errors and self.strict:
            raise RuntimeError(
                f"Hook phase `{phase}` failed: " + "; ".join(errors)
            )
        return errors

    @staticmethod
    def _load_callable(path):
        if not path:
            return None
        text = str(path).strip()
        if ":" not in text:
            return None
        module_name, fn_name = text.split(":", 1)
        module_name = module_name.strip()
        fn_name = fn_name.strip()
        if not module_name or not fn_name:
            return None
        try:
            module = importlib.import_module(module_name)
            fn = getattr(module, fn_name, None)
        except (ImportError, AttributeError, ValueError) as exc:
            # ImportError: module not found / not on path; AttributeError: package without `module`.
            _LOG.warning("Failed to load extension %s:%s — %s", module_name, fn_name, exc)
            return None
        return fn if callable(fn) else None
