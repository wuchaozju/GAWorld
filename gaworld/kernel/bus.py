"""EventBus — drop-in superset of the legacy :class:`gaworld.hooks.HookBus`.

Three hook semantics turn extensions from observers into participants:

- ``emit``    (observe): notify-only; return values ignored. 100% compatible
  with HookBus — handlers keep the ``fn(context_dict)`` signature and the
  ``CONFIG["extensions"]["hooks"]`` loading format.
- ``collect`` (contribute): each handler returns 0..n contributions which the
  kernel merges into one list (e.g. perception snippets, interrupt candidates).
- ``filter``  (pipeline): a value flows through handlers, each may rewrite it
  (e.g. plan prompt, selected action). Returning ``None`` keeps the previous
  value, so a buggy handler cannot blank the pipeline.

Handlers run in (priority desc, registration order) order. Like HookBus, the
bus is a trust boundary: handler exceptions are caught and logged, and only
raise when ``strict`` is set.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from gaworld.hooks import HookBus
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.kernel.bus")


class EventBus:
    """Priority-ordered hook dispatcher with observe/collect/filter semantics."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.strict = bool(cfg.get("strict", False))
        # event -> list of (priority, seq, fn); sorted lazily at dispatch.
        self._handlers: dict[str, list[tuple[int, int, Callable]]] = defaultdict(list)
        self._seq = 0
        # Merged into every dispatch context (e.g. {"sim": SimContext}).
        self.base_context: dict[str, Any] = {}
        hook_map = cfg.get("hooks", {})
        if isinstance(hook_map, dict):
            for event, paths in hook_map.items():
                if isinstance(paths, str):
                    paths = [paths]
                if not isinstance(paths, list):
                    continue
                for path in paths:
                    fn = HookBus._load_callable(path)
                    if fn:
                        self.on(event, fn)

    # -- registration ----------------------------------------------------

    def on(self, event: str, fn: Callable, *, priority: int = 0) -> None:
        if not callable(fn):
            return
        self._seq += 1
        self._handlers[str(event)].append((int(priority), self._seq, fn))

    # HookBus-compatible alias.
    register = on

    def _ordered(self, event: str) -> list[Callable]:
        entries = self._handlers.get(str(event), [])
        return [fn for _, _, fn in sorted(entries, key=lambda e: (-e[0], e[1]))]

    def _handle_error(self, event: str, fn: Callable, exc: Exception, errors: list[str]) -> None:
        _LOG.warning(
            "hook %s.%s in event %s raised: %s",
            getattr(fn, "__module__", "?"),
            getattr(fn, "__name__", repr(fn)),
            event,
            exc,
        )
        errors.append(f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__name__', repr(fn))}: {exc}")

    def _finish(self, event: str, errors: list[str]) -> None:
        if errors and self.strict:
            raise RuntimeError(f"Hook event `{event}` failed: " + "; ".join(errors))

    # -- dispatch ---------------------------------------------------------

    def emit(self, event: str, **context) -> list[str]:
        """Observe semantics: notify handlers, ignore return values."""
        ctx = {**self.base_context, **context}
        errors: list[str] = []
        for fn in self._ordered(event):
            try:
                fn(ctx)
            except Exception as exc:  # noqa: BLE001 — extension trust boundary
                self._handle_error(event, fn, exc, errors)
        self._finish(event, errors)
        return errors

    def collect(self, event: str, **context) -> list[Any]:
        """Contribute semantics: merge every handler's contribution(s)."""
        ctx = {**self.base_context, **context}
        errors: list[str] = []
        merged: list[Any] = []
        for fn in self._ordered(event):
            try:
                out = fn(ctx)
            except Exception as exc:  # noqa: BLE001 — extension trust boundary
                self._handle_error(event, fn, exc, errors)
                continue
            if out is None:
                continue
            if isinstance(out, (list, tuple)):
                merged.extend(out)
            else:
                merged.append(out)
        self._finish(event, errors)
        return merged

    def filter(self, event: str, value: Any, **context) -> Any:
        """Pipeline semantics: value flows through handlers, each may rewrite.

        Handlers have signature ``fn(value, context_dict)``. Returning ``None``
        keeps the previous value.
        """
        ctx = {**self.base_context, **context}
        errors: list[str] = []
        for fn in self._ordered(event):
            try:
                out = fn(value, ctx)
            except Exception as exc:  # noqa: BLE001 — extension trust boundary
                self._handle_error(event, fn, exc, errors)
                continue
            if out is not None:
                value = out
        self._finish(event, errors)
        return value
