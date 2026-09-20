"""Controller — action validation gate + runtime intervention API.

Stateless mediator (Agent-Kernel "Controller"). Two responsibilities:

1. **Validation gate**: every structured action request flows through a
   priority-ordered validator chain before execution. A validator returns a
   :class:`Verdict` (allow / deny / rewrite) or ``None`` for "no opinion".
   Denied actions are reported back so the agent can perceive the refusal.
2. **Runtime intervention**: named, auditable operations on the running
   simulation (set state, inject event, add/remove agent, update config).
   The dashboard becomes one HTTP front-end of this API.

K1 ships the skeleton; validators and interventions are registered by
plugins from K3 onward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from gaworld.logging_setup import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from gaworld.kernel.context import SimContext

_LOG = get_logger("gaworld.kernel.controller")


@dataclass
class ActionRequest:
    """A structured action an agent wants to execute."""

    agent_id: Any
    name: str
    params: dict = field(default_factory=dict)
    raw_text: str = ""


@dataclass
class Verdict:
    """Outcome of validation: allow, deny(reason), or rewrite(request)."""

    allowed: bool = True
    reason: str = ""
    rewritten: ActionRequest | None = None

    @staticmethod
    def allow() -> "Verdict":
        return Verdict(allowed=True)

    @staticmethod
    def deny(reason: str) -> "Verdict":
        return Verdict(allowed=False, reason=str(reason))

    @staticmethod
    def rewrite(request: ActionRequest) -> "Verdict":
        return Verdict(allowed=True, rewritten=request)


class Controller:
    """Stateless validation + intervention hub."""

    def __init__(self):
        # (priority, seq, fn); higher priority validates first.
        self._validators: list[tuple[int, int, Callable]] = []
        self._interventions: dict[str, Callable] = {}
        self._seq = 0

    # -- validation gate ----------------------------------------------------

    def register_validator(self, fn: Callable, *, priority: int = 0) -> None:
        if not callable(fn):
            return
        self._seq += 1
        self._validators.append((int(priority), self._seq, fn))

    def validate(self, request: ActionRequest, ctx: "SimContext") -> Verdict:
        """Run the validator chain; first deny wins, rewrites flow through."""
        for _, _, fn in sorted(self._validators, key=lambda e: (-e[0], e[1])):
            try:
                verdict = fn(request, ctx)
            except Exception as exc:  # noqa: BLE001 — validator trust boundary
                _LOG.warning(
                    "validator %s.%s raised: %s (treated as no opinion)",
                    getattr(fn, "__module__", "?"),
                    getattr(fn, "__name__", repr(fn)),
                    exc,
                )
                continue
            if verdict is None:
                continue
            if not verdict.allowed:
                if ctx.recorder is not None:
                    ctx.recorder.record(
                        "action.denied",
                        {
                            "agent_id": request.agent_id,
                            "action": request.name,
                            "reason": verdict.reason,
                        },
                    )
                return verdict
            if verdict.rewritten is not None:
                request = verdict.rewritten
        return Verdict(allowed=True, rewritten=request)

    # -- runtime intervention -------------------------------------------------

    def register_intervention(self, name: str, fn: Callable) -> None:
        if callable(fn):
            self._interventions[str(name)] = fn

    def intervention_names(self) -> list[str]:
        return sorted(self._interventions)

    def intervene(self, name: str, ctx: "SimContext", **kwargs) -> Any:
        """Execute a named intervention; every call is recorded for audit."""
        fn = self._interventions.get(str(name))
        if fn is None:
            raise ValueError(
                f"unknown intervention `{name}`; registered: {self.intervention_names()}"
            )
        if ctx.recorder is not None:
            ctx.recorder.record("controller.intervention", {"name": name, "kwargs": kwargs})
        return fn(ctx, **kwargs)
