"""
No-network baseline condition.

Baseline runs use config_id = -1: no edges, no confederates, and no network
verification. Everything else (population, personas, models, prompts, three
deliberation rounds plus one voting round, all gates) is identical to a
networked run. Agents still see their own prior-round statements, because
the observation scope always includes the agent itself.
"""

from __future__ import annotations

from typing import Any

BASELINE_CONFIG_ID = -1

POPULATIONS = ['pop_a1', 'pop_a2', 'pop_b1', 'pop_b2', 'pop_c1', 'pop_c2']
PROPOSALS = [
    'srma', 'wealth_tax', 'un_veto', 'aesthetic_objectivity',
    'meaning_of_life', 'regifting', 'shared_workplace',
]


def is_baseline(config_id: Any) -> bool:
    """True when a run row denotes the no-network baseline condition."""
    return int(config_id) == BASELINE_CONFIG_ID


def baseline_config() -> dict[str, Any]:
    """Stand-in config for baseline runs (no generator, no dials)."""
    return {'generator': 'none', 'primary_level': 0, 'secondary_level': 0}


def baseline_network_stats() -> dict[str, Any]:
    """Structural statistics of the empty graph on 100 nodes."""
    return {
        'n_edges': 0,
        'mean_degree': 0.0,
        'degree_gini': 0.0,
        'mean_local_clustering': 0.0,
        'is_connected': False,
    }
