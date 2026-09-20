#!/usr/bin/env python3
"""
GAWorld Experiment: Emotion Contagion (EXP-EMO-001)

Studies how emotions spread through social networks and the factors
that influence contagion speed and scope.

Usage:
    python exp_emotion_contagion.py run --treatment treatment_happy --days 14 --seed 42
    python exp_emotion_contagion.py analyze --treatment treatment_happy
    python exp_emotion_contagion.py compare
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_experiment import ExperimentRunner, RESULTS_DIR

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


TREATMENTS = {
    "control": {
        "emotion_seed": None,
        "network_modification": None,
        "description": "无干预基线"
    },
    "treatment_happy": {
        "emotion_seed": {
            "seed_agents": [1, 5, 10],
            "seed_value": 0.9,
            "inject_day": 2,
            "inject_hour": 8
        },
        "network_modification": None,
        "description": "播种开心情绪"
    },
    "treatment_sad": {
        "emotion_seed": {
            "seed_agents": [3, 8, 15],
            "seed_value": 0.2,
            "inject_day": 2,
            "inject_hour": 8
        },
        "network_modification": None,
        "description": "播种悲伤情绪"
    },
    "treatment_sparse": {
        "emotion_seed": {
            "seed_agents": [1, 5, 10],
            "seed_value": 0.9,
            "inject_day": 2,
            "inject_hour": 8
        },
        "network_modification": {
            "reduce_density_by": 0.5
        },
        "description": "稀疏网络 + 开心情绪播种"
    }
}


class ExpEmotionContagion(ExperimentRunner):
    """Emotion contagion experiment runner."""

    def __init__(self, treatment: str = "control", days: int = 14, seed: int = 42):
        exp_name = "exp_emotion_contagion"
        exp_dir = RESULTS_DIR / exp_name / treatment

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.treatment = treatment
        self.config = TREATMENTS.get(treatment, TREATMENTS["control"])

    def run(self) -> bool:
        """Run the emotion contagion experiment."""
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        config_record = {
            "treatment": self.treatment,
            "config": self.config,
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config_record, f, indent=2, ensure_ascii=False)

        # Prepare seed state modification if needed
        seed_config = self.config.get("emotion_seed")
        env_vars = {}

        if seed_config:
            # Create temporary seed state file with modified emotion values
            orig_csv = PROJECT_ROOT / "data" / "hangzhou_agents_state_init.csv"
            if orig_csv.exists():
                temp_csv = self.experiment_dir / "seed_state.csv"
                df = pd.read_csv(orig_csv)

                for agent_id in seed_config["seed_agents"]:
                    agent_idx = df[df["id"] == agent_id].index
                    if len(agent_idx) > 0:
                        df.loc[agent_idx, "emotion"] = seed_config["seed_value"]

                df.to_csv(temp_csv, index=False)
                env_vars["GAWORLD_AGENT_STATE_CSV"] = str(temp_csv)

        return self.run_simulation(
            days=self.default_days,
            seed=self.default_seed,
            env_vars=env_vars if env_vars else None
        )

    def _load_state_long(self, state_file: Path) -> pd.DataFrame:
        """Load state history CSV (long format: agent_id, step, metric, value)."""
        df = pd.read_csv(state_file)
        # Pivot to wide format: one column per metric for easier analysis
        df_wide = df.pivot_table(index=["agent_id", "step"], columns="metric", values="value")
        df_wide = df_wide.reset_index()
        # Convert step to approximate day (assuming 96 steps/day based on 15-min slots)
        df_wide["day"] = (df_wide["step"] // 96) + 1
        return df_wide

    def analyze(self) -> Dict[str, Any]:
        """Analyze emotion contagion results."""
        state_file = self.experiment_dir / "state" / "agent_state_history.csv"

        if not state_file.exists():
            return {"error": "State file not found", "path": str(state_file)}

        df = self._load_state_long(state_file)

        # Calculate daily emotion statistics
        daily_stats = df.groupby("day").agg({
            "emotion": ["mean", "std", "min", "max"]
        }).reset_index()
        daily_stats.columns = ["day", "mean", "std", "min", "max"]
        daily_stats["emotion_change"] = daily_stats["mean"].pct_change()
        daily_stats["sync_score"] = 1 - daily_stats["std"]

        # Find peak and lowest happiness days
        peak_day = daily_stats.loc[daily_stats["mean"].idxmax(), "day"] if len(daily_stats) > 0 else None
        lowest_day = daily_stats.loc[daily_stats["mean"].idxmin(), "day"] if len(daily_stats) > 0 else None

        # Calculate seed vs non-seed correlation
        seed_agents = self.config.get("emotion_seed", {}).get("seed_agents", [])

        results = {
            "treatment": self.treatment,
            "daily_stats": daily_stats.to_dict(),
            "peak_happiness_day": int(peak_day) if peak_day is not None and not pd.isna(peak_day) else None,
            "lowest_happiness_day": int(lowest_day) if lowest_day is not None and not pd.isna(lowest_day) else None,
            "final_mean_emotion": float(daily_stats.iloc[-1]["mean"]) if len(daily_stats) > 0 else None,
            "final_sync_score": float(daily_stats.iloc[-1]["sync_score"]) if len(daily_stats) > 0 else None
        }

        if seed_agents:
            seed_emotion = df[df["agent_id"].isin(seed_agents)].groupby("day")["emotion"].mean()
            non_seed_emotion = df[~df["agent_id"].isin(seed_agents)].groupby("day")["emotion"].mean()

            if len(seed_emotion) > 0 and len(non_seed_emotion) > 0:
                correlation = seed_emotion.corr(non_seed_emotion)
                results["seed_other_correlation"] = float(correlation) if not pd.isna(correlation) else None
                results["initial_gap"] = float(seed_emotion.iloc[0] - non_seed_emotion.iloc[0]) if len(seed_emotion) > 0 else None
                results["final_gap"] = float(seed_emotion.iloc[-1] - non_seed_emotion.iloc[-1]) if len(seed_emotion) > 0 else None

        return results

    def compute_contagion_speed(self) -> Dict[str, Any]:
        """Analyze emotion contagion speed."""
        state_file = self.experiment_dir / "state" / "agent_state_history.csv"

        if not state_file.exists():
            return {"error": "State file not found"}

        df = self._load_state_long(state_file)
        seed_agents = self.config.get("emotion_seed", {}).get("seed_agents", [])

        if not seed_agents:
            return {"error": "No seed agents configured"}

        seed_df = df[df["agent_id"].isin(seed_agents)]
        non_seed_df = df[~df["agent_id"].isin(seed_agents)]

        seed_daily = seed_df.groupby("day")["emotion"].mean()
        non_seed_daily = non_seed_df.groupby("day")["emotion"].mean()

        return {
            "seed_mean_trajectory": seed_daily.to_dict(),
            "non_seed_mean_trajectory": non_seed_daily.to_dict()
        }


def run_treatment(treatment: str, days: int, seed: int) -> bool:
    """Run a single treatment."""
    exp = ExpEmotionContagion(treatment=treatment, days=days, seed=seed)
    return exp.run()


def analyze_treatment(treatment: str) -> Dict[str, Any]:
    """Analyze a single treatment."""
    exp = ExpEmotionContagion(treatment=treatment)
    return exp.analyze()


def compare_treatments() -> Dict[str, Any]:
    """Compare all treatments."""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = RESULTS_DIR / "exp_emotion_contagion" / treatment
        if exp_dir.exists():
            exp = ExpEmotionContagion(treatment=treatment)
            results[treatment] = exp.analyze()

    print("\n=== Emotion Contagion Experiment Comparison ===\n")
    print(f"{'Treatment':<20} {'Final Emotion':<14} {'Sync Score':<12} {'Seed Corr':<12}")
    print("-" * 60)
    for treatment, res in results.items():
        if "error" not in res:
            final = res.get("final_mean_emotion", 0) or 0
            sync = res.get("final_sync_score", 0) or 0
            corr = res.get("seed_other_correlation", 0) or 0
            print(f"{treatment:<20} {final:<14.4f} {sync:<12.4f} {corr:<12.4f}")

    comparison_file = RESULTS_DIR / "exp_emotion_contagion" / "comparison_results.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    return results


def main():
    parser = argparse.ArgumentParser(description="Emotion Contagion Experiment (EXP-EMO-001)")
    parser.add_argument("action", choices=["run", "analyze", "compare"], help="Action to perform")
    parser.add_argument("--treatment", default="control", help=f"Treatment: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="Simulation days")
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