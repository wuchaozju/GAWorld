"""Build the 18 network configurations used by the council experiment.

Each of the three network generators (Watts-Strogatz, Holme-Kim, and the
Stochastic Block Model) gets six configurations: every combination of three
settings on its main dial and two settings on its second dial. The script
writes them all to data/configs/network_configs.json so later phases can
read one JSON file instead of hard-coding settings.

For the Stochastic Block Model the dials are the within/between ratio and
the group size. Given a fixed average degree the script solves for the
inside-group connection probability p_in and the between-group connection
probability p_out using:

    p_out = deg / ((gs - 1) * r + (100 - gs))
    p_in  = r * p_out

where deg is the target degree, gs is the group size, and r is the ratio.

Functions:
    _ws_configs: make the six Watts-Strogatz configurations.
    _hk_configs: make the six Holme-Kim configurations.
    _sbm_configs: make the six Stochastic Block Model configurations.
    _write_configs_file: write every configuration to the JSON file.
    main: generate all configurations and save them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_PATH = _REPO_ROOT / "data" / "configs" / "network_configs.json"

_NODES = 100


@dataclass(frozen=True)
class NetworkConfig:
    """One row of the dial grid for a network generator."""

    config_id: int
    generator: str
    primary_dial_name: str
    primary_dial_value: float
    primary_level: int
    secondary_dial_name: str
    secondary_dial_value: float
    secondary_level: int
    params: dict[str, object]


def _ws_configs() -> list[NetworkConfig]:
    """Make the six Watts-Strogatz configurations.

    The main dial is the rewiring probability (0.1, 0.3, 0.5) and the second
    dial is the mean degree k (6, 8). The rewiring probability changes
    slowest so the first dials come first.
    """
    configs: list[NetworkConfig] = []
    config_id = 0
    for p, p_level in ((0.1, 0), (0.3, 1), (0.5, 2)):
        for k, k_level in ((6, 0), (8, 1)):
            configs.append(
                NetworkConfig(
                    config_id=config_id,
                    generator="watts_strogatz",
                    primary_dial_name="rewiring_probability",
                    primary_dial_value=p,
                    primary_level=p_level,
                    secondary_dial_name="mean_degree",
                    secondary_dial_value=float(k),
                    secondary_level=k_level,
                    params={"n": _NODES, "k": k, "p": p},
                )
            )
            config_id += 1
    return configs


def _hk_configs() -> list[NetworkConfig]:
    """Make the six Holme-Kim configurations.

    The main dial is the triad probability (0.2, 0.5, 0.8) and the second
    dial is m, the number of edges each new node adds (3, 4). The triad
    probability changes slowest.
    """
    configs: list[NetworkConfig] = []
    config_id = 6
    for p_triad, p_level in ((0.2, 0), (0.5, 1), (0.8, 2)):
        for m, m_level in ((3, 0), (4, 1)):
            configs.append(
                NetworkConfig(
                    config_id=config_id,
                    generator="holme_kim",
                    primary_dial_name="triad_probability",
                    primary_dial_value=p_triad,
                    primary_level=p_level,
                    secondary_dial_name="m",
                    secondary_dial_value=float(m),
                    secondary_level=m_level,
                    params={"n": _NODES, "m": m, "p_triad": p_triad},
                )
            )
            config_id += 1
    return configs


def _sbm_connection_probabilities(
    ratio: int, group_size: int, degree: int
) -> tuple[float, float]:
    """Solve for p_out and p_in that give the target mean degree.

    Returns (p_out, p_in). The formulas come from the expected degree in a
    block model: each node sees (group_size - 1) inside-group partners and
    (100 - group_size) outside-group partners, so p_out sets the expected
    degree to the target and p_in is the ratio times p_out.
    """
    p_out = degree / ((group_size - 1) * ratio + (_NODES - group_size))
    p_in = ratio * p_out
    return p_out, p_in


def _sbm_configs() -> list[NetworkConfig]:
    """Make the six Stochastic Block Model configurations.

    The main dial is the within/between ratio (3, 10, 50) and the second
    dial is the group size (10 or 20). The target degree is fixed at 6 for
    every configuration. The ratio changes slowest.
    """
    configs: list[NetworkConfig] = []
    config_id = 12
    degree = 6
    for ratio, ratio_level in ((3, 0), (10, 1), (50, 2)):
        for group_size, size_level in ((10, 0), (20, 1)):
            p_out, p_in = _sbm_connection_probabilities(
                ratio, group_size, degree
            )
            n_blocks = _NODES // group_size
            block_sizes = [group_size] * n_blocks
            configs.append(
                NetworkConfig(
                    config_id=config_id,
                    generator="sbm",
                    primary_dial_name="within_between_ratio",
                    primary_dial_value=float(ratio),
                    primary_level=ratio_level,
                    secondary_dial_name="group_size",
                    secondary_dial_value=float(group_size),
                    secondary_level=size_level,
                    params={
                        "n": _NODES,
                        "n_blocks": n_blocks,
                        "block_sizes": block_sizes,
                        "p_in": p_in,
                        "p_out": p_out,
                        "r": ratio,
                        "deg_target": degree,
                    },
                )
            )
            config_id += 1
    return configs


def _write_configs_file(configs: list[NetworkConfig]) -> Path:
    """Write every configuration to the JSON file and return its path."""
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configs": [asdict(config) for config in configs],
    }
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return _OUTPUT_PATH


def main() -> None:
    """Generate all 18 configurations and save them to the JSON file."""
    configs = _ws_configs() + _hk_configs() + _sbm_configs()
    path = _write_configs_file(configs)
    print(f"Wrote {len(configs)} configs to {path}")


if __name__ == "__main__":
    main()
