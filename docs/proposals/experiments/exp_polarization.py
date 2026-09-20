#!/usr/bin/env python3
"""
GAWorld Experiment: Polarization (EXP-POL-001)

Studies opinion polarization and echo chamber effects in social networks.

Usage:
    python exp_polarization.py run --treatment treatment_diversity --days 14 --seed 42
    python exp_polarization.py analyze --treatment control_baseline
    python exp_polarization.py compare
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_experiment import ExperimentRunner, RESULTS_DIR


TREATMENTS = {
    "control_baseline": {
        "description": "无干预，自然演化",
        "intervention_enabled": True,
        "diversity_boost": 0.0,
        "filter_similar": False,
        "social_diversity_boost": False
    },
    "treatment_diversity": {
        "description": "增强多样性干预",
        "intervention_enabled": True,
        "diversity_boost": 0.3,
        "filter_similar": False,
        "social_diversity_boost": False
    },
    "treatment_filter": {
        "description": "过滤相似立场内容",
        "intervention_enabled": True,
        "diversity_boost": 0.0,
        "filter_similar": True,
        "social_diversity_boost": False
    },
    "treatment_social": {
        "description": "增强社交多样性连接",
        "intervention_enabled": True,
        "diversity_boost": 0.0,
        "filter_similar": False,
        "social_diversity_boost": True
    }
}


class ExpPolarization(ExperimentRunner):
    """Polarization experiment runner."""

    def __init__(self, treatment: str = "control_baseline", days: int = 14, seed: int = 42):
        exp_name = "exp_polarization"
        exp_dir = RESULTS_DIR / exp_name / treatment

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.treatment = treatment
        self.config = TREATMENTS.get(treatment, TREATMENTS["control_baseline"])

    def run(self) -> bool:
        """Run the polarization experiment."""
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        config_record = {
            "treatment": self.treatment,
            "config": self.config,
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config_record, f, indent=2)

        # Set environment variables
        env_vars = {
            "GAWORLD_INTERVENTION_ENABLED": "true",
            "GAWORLD_DIVERSITY_BOOST": str(self.config["diversity_boost"]),
            "GAWORLD_FILTER_SIMILAR": str(self.config["filter_similar"]).lower(),
            "GAWORLD_SOCIAL_DIVERSITY": str(self.config["social_diversity_boost"]).lower()
        }

        return self.run_simulation(
            days=self.default_days,
            seed=self.default_seed,
            env_vars=env_vars
        )

    def analyze(self) -> Dict[str, Any]:
        """Analyze polarization results."""
        metrics_file = self.experiment_dir / "intervention" / "intervention_metrics.csv"

        if not metrics_file.exists():
            return {"error": "Metrics file not found", "path": str(metrics_file)}

        df = pd.read_csv(metrics_file)

        # Calculate polarization index: (max - min) / (max + min)
        daily_extremes = df.groupby("day")["stance_score"].agg(["min", "max"])
        diff = daily_extremes["max"] - daily_extremes["min"]
        sum_vals = daily_extremes["max"] + daily_extremes["min"].replace(0, 0.001)
        polarization_index = diff / sum_vals

        daily_std = df.groupby("day")["stance_score"].std()

        results = {
            "treatment": self.treatment,
            "final_polarization_index": float(polarization_index.iloc[-1]) if len(polarization_index) > 0 else None,
            "avg_stance_std": float(daily_std.mean()),
            "polarization_trend": polarization_index.to_dict(),
            "stance_std_trend": daily_std.to_dict()
        }

        if "cross_viewpoint_exposure" in df.columns:
            results["avg_cross_viewpoint_exposure"] = float(df["cross_viewpoint_exposure"].mean())

        if "toxicity_score" in df.columns:
            results["avg_toxicity"] = float(df["toxicity_score"].mean())

        return results

    def compute_polarization_index_series(self) -> pd.Series:
        """Compute polarization index time series."""
        metrics_file = self.experiment_dir / "intervention" / "intervention_metrics.csv"
        if not metrics_file.exists():
            return pd.Series()

        df = pd.read_csv(metrics_file)
        daily_extremes = df.groupby("day")["stance_score"].agg(["min", "max"])
        diff = daily_extremes["max"] - daily_extremes["min"]
        sum_vals = daily_extremes["max"] + daily_extremes["min"].replace(0, 0.001)
        return diff / sum_vals


def run_treatment(treatment: str, days: int, seed: int) -> bool:
    """Run a single treatment."""
    exp = ExpPolarization(treatment=treatment, days=days, seed=seed)
    return exp.run()


def analyze_treatment(treatment: str) -> Dict[str, Any]:
    """Analyze a single treatment."""
    exp = ExpPolarization(treatment=treatment)
    return exp.analyze()


def compare_treatments() -> Dict[str, Any]:
    """Compare all treatments."""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = RESULTS_DIR / "exp_polarization" / treatment
        if exp_dir.exists():
            exp = ExpPolarization(treatment=treatment)
            results[treatment] = exp.analyze()

    print("\n=== Polarization Experiment Comparison ===\n")
    print(f"{'Treatment':<25} {'Final Polarization':<18} {'Avg Std':<12} {'Cross-View':<12}")
    print("-" * 70)
    for treatment, res in results.items():
        if "error" not in res:
            pol = res.get("final_polarization_index", 0) or 0
            std = res.get("avg_stance_std", 0) or 0
            exp = res.get("avg_cross_viewpoint_exposure", 0) or 0
            print(f"{treatment:<25} {pol:<18.4f} {std:<12.4f} {exp:<12.4f}")

    comparison_file = RESULTS_DIR / "exp_polarization" / "comparison_results.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return results


def main():
    parser = argparse.ArgumentParser(description="Polarization Experiment (EXP-POL-001)")
    parser.add_argument("action", choices=["run", "analyze", "compare"], help="Action to perform")
    parser.add_argument("--treatment", default="control_baseline", help=f"Treatment: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="Simulation days (recommended >= 14)")
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