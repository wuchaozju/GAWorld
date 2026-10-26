"""Swarm crowdsourcing: one task, a crowd of residents, several rounds.

The subsystem answers a different question than :mod:`gaworld.collaboration`.
Collaboration asks a *small* group to work together on one deliverable.
Crowdsourcing asks a *large* group to work on the same task independently and
then narrows the crowd towards the agents that did well.

Public surface:

``CrowdsourcingService``
    create / list / inspect / pause / resume / cancel crowd sessions
``CrowdsourcingRunner``
    the round loop: select, answer, judge, credit, prune, aggregate
``STRATEGIES``
    the coordination mechanisms a crowd can run under, including the
    market-based one from arXiv:2610.22322
"""

from gaworld.crowdsourcing.models import CrowdSession, CrowdStatus
from gaworld.crowdsourcing.service import CrowdsourcingService
from gaworld.crowdsourcing.strategies import (
    STRATEGIES,
    StrategySpec,
    get_strategy,
    strategy_catalog,
)

__all__ = [
    "STRATEGIES",
    "CrowdSession",
    "CrowdStatus",
    "CrowdsourcingService",
    "StrategySpec",
    "get_strategy",
    "strategy_catalog",
]
