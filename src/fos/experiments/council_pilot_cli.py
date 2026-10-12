"""This file reads command-line options and starts the full council pilot."""

import argparse
import json
from pathlib import Path

from fos.experiments.council_pilot_runner import (
    DEFAULT_COUNCIL_MODELS,
    run_full_council_pilot,
)


def run_council_pilot_cli() -> None:
    """Read pilot settings, run every branch, and print the result location."""
    parser = argparse.ArgumentParser(description="Run the mixed-model council pilot.")
    parser.add_argument(
        "--output-dir",
        default="artifacts/full_council_three_topic_run",
    )
    parser.add_argument("--models", default=",".join(DEFAULT_COUNCIL_MODELS))
    parser.add_argument("--agents", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--base-url", default="http://localhost:11434")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    summary = run_full_council_pilot(
        output_dir=output_dir,
        model_names=[
            model.strip() for model in args.models.split(",") if model.strip()
        ],
        total_agents=args.agents,
        seed=args.seed,
        temperature=args.temperature,
        base_url=args.base_url,
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir.resolve()),
                "run_count": len(summary["runs"]),
            },
            indent=2,
        )
    )
