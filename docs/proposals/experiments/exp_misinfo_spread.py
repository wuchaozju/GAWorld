#!/usr/bin/env python3
"""
GAWorld Experiment: Misinformation Spread (EXP-INFO-001)

Studies how misinformation spreads through social networks and the factors
that influence acceptance and propagation.

Usage:
    python exp_misinfo_spread.py run --treatment treatment_a --days 7 --seed 42
    python exp_misinfo_spread.py analyze --treatment treatment_a
    python exp_misinfo_spread.py compare
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

# Import base framework
sys.path.insert(0, str(Path(__file__).parent))
from run_experiment import ExperimentRunner, RESULTS_DIR

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


TREATMENTS = {
    "control": {
        "misinfo_seed": None,
        "intervention_enabled": True,
        "description": "无信息注入基线"
    },
    "treatment_a": {
        "misinfo_seed": {
            "text": "听说地铁下个月要涨价到10元了，大家赶紧去充值交通卡",
            "target_agent_id": 1,
            "day": 1,
            "hour": 8
        },
        "intervention_enabled": True,
        "description": "单条误信息注入"
    },
    "treatment_b": {
        "misinfo_seed": {
            "text": "听说地铁下个月要涨价到10元了，大家赶紧去充值交通卡",
            "target_agent_id": 1,
            "day": 1,
            "hour": 8
        },
        "intervention_enabled": True,
        "high_diversity_mode": True,
        "description": "误信息 + 强干预（高跨观点曝光）"
    }
}


class ExpMisinfoSpread(ExperimentRunner):
    """Misinformation spread experiment runner."""

    def __init__(self, treatment: str = "control", days: int = 7, seed: int = 42):
        exp_name = "exp_misinfo_spread"
        exp_dir = RESULTS_DIR / exp_name / treatment

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.treatment = treatment
        self.config = TREATMENTS.get(treatment, TREATMENTS["control"])

    def run(self) -> bool:
        """Run the misinformation spread experiment."""
        # Ensure output directories exist
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Record experiment configuration
        config_record = {
            "treatment": self.treatment,
            "config": self.config,
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config_record, f, indent=2, ensure_ascii=False)

        # Prepare environment variables for misinformation injection
        env_vars = {}
        if self.config.get("misinfo_seed"):
            seed_info = self.config["misinfo_seed"]
            env_vars["GAWORLD_MISINFO_SEED"] = json.dumps(seed_info)

        if self.config.get("high_diversity_mode"):
            env_vars["GAWORLD_DIVERSITY_BOOST"] = "0.3"

        # Run simulation
        return self.run_simulation(
            days=self.default_days,
            seed=self.default_seed,
            env_vars=env_vars if env_vars else None
        )

    def analyze(self) -> Dict[str, Any]:
        """Analyze misinformation spread results."""
        metrics_file = self.experiment_dir / "intervention" / "intervention_metrics.csv"

        if not metrics_file.exists():
            return {"error": "Metrics file not found", "path": str(metrics_file)}

        df = pd.read_csv(metrics_file)

        results = {
            "treatment": self.treatment,
            "total_agents": int(df["agent_id"].nunique()),
            "days": int(df["day"].nunique()),
            "avg_misinfo_risk": df.groupby("day")["misinformation_risk"].mean().to_dict(),
            "peak_misinfo_risk": float(df["misinformation_risk"].max()),
            "final_misinfo_risk": float(df[df["day"] == df["day"].max()]["misinformation_risk"].mean()),
        }

        if "cross_viewpoint_exposure" in df.columns:
            results["avg_cross_viewpoint_exposure"] = df["cross_viewpoint_exposure"].mean()

        return results

    def compute_spread_metrics(self) -> Dict[str, Any]:
        """Compute misinformation spread dynamics."""
        metrics_file = self.experiment_dir / "intervention" / "intervention_metrics.csv"

        if not metrics_file.exists():
            return {"error": "Metrics file not found"}

        df = pd.read_csv(metrics_file)

        # Calculate spread rate over time
        daily_risk = df.groupby("day")["misinformation_risk"].mean()

        spread_metrics = {
            "daily_mean_risk": daily_risk.to_dict(),
            "risk_trend": "increasing" if daily_risk.iloc[-1] > daily_risk.iloc[0] else "decreasing",
            "peak_day": int(daily_risk.idxmax()),
            "peak_risk": float(daily_risk.max())
        }

        return spread_metrics


def run_treatment(treatment: str, days: int, seed: int) -> bool:
    """Run a single treatment."""
    exp = ExpMisinfoSpread(treatment=treatment, days=days, seed=seed)
    return exp.run()


def analyze_treatment(treatment: str) -> Dict[str, Any]:
    """Analyze a single treatment."""
    exp = ExpMisinfoSpread(treatment=treatment)
    return exp.analyze()


def compare_treatments() -> Dict[str, Any]:
    """Compare all treatments."""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = RESULTS_DIR / "exp_misinfo_spread" / treatment
        if exp_dir.exists():
            exp = ExpMisinfoSpread(treatment=treatment)
            results[treatment] = exp.analyze()

    print("\n=== Misinformation Spread Experiment Comparison ===\n")
    print(f"{'Treatment':<20} {'Final Risk':<12} {'Peak Risk':<12} {'Avg Exposure':<15}")
    print("-" * 60)
    for treatment, res in results.items():
        if "error" not in res:
            final = res.get("final_misinfo_risk", 0)
            peak = res.get("peak_misinfo_risk", 0)
            exposure = res.get("avg_cross_viewpoint_exposure", 0)
            print(f"{treatment:<20} {final:<12.4f} {peak:<12.4f} {exposure:<15.4f}")

    # Save comparison
    comparison_file = RESULTS_DIR / "exp_misinfo_spread" / "comparison_results.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return results


def main():
    parser = argparse.ArgumentParser(description="Misinformation Spread Experiment (EXP-INFO-001)")
    parser.add_argument("action", choices=["run", "analyze", "compare"], help="Action to perform")
    parser.add_argument("--treatment", default="control", help=f"Treatment: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=7, help="Simulation days")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    if args.action == "run":
        success = run_treatment(args.treatment, args.days, args.seed)
        sys.exit(0 if success else 1)
    elif args.action == "analyze":
        results = analyze_treatment(args.treatment)
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    elif args.action == "compare":
        results = compare_treatments()
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()