#!/usr/bin/env python3
"""
GAWorld Experiment: Transport Behavior (EXP-TRANS-001)

Studies urban travel behavior and transport policy effects.

Usage:
    python exp_transport_behavior.py run --treatment control --days 14 --seed 42
    python exp_transport_behavior.py analyze --treatment treatment_weather_rain
    python exp_transport_behavior.py compare
"""

import argparse
import json
import os
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
        "weather": None,
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "正常出行"
    },
    "treatment_weather_rain": {
        "weather": {
            "type": "rain",
            "start_day": 3,
            "end_day": 5,
            "hours": [7, 8, 9, 17, 18, 19]
        },
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "暴雨天气事件"
    },
    "treatment_weather_hot": {
        "weather": {
            "type": "hot",
            "start_day": 7,
            "end_day": 10,
            "hours": [10, 11, 12, 13, 14, 15]
        },
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "高温天气事件"
    },
    "treatment_transit_price": {
        "weather": None,
        "transit_price_multiplier": 1.5,
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "地铁涨价50%"
    },
    "treatment_car_restriction": {
        "weather": None,
        "transit_price_multiplier": 1.0,
        "car_restriction": True,
        "rush_hour_multiplier": 1.0,
        "description": "私家车高峰限行"
    },
    "treatment_rush_hour_cost": {
        "weather": None,
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.5,
        "description": "高峰时段出行成本上升"
    }
}


class ExpTransportBehavior(ExperimentRunner):
    """Transport behavior experiment runner."""

    def __init__(self, treatment: str = "control", days: int = 14, seed: int = 42):
        exp_name = "exp_transport_behavior"
        exp_dir = RESULTS_DIR / exp_name / treatment

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.treatment = treatment
        self.config = TREATMENTS.get(treatment, TREATMENTS["control"])

    def run(self) -> bool:
        """Run the transport behavior experiment."""
        config_record = {
            "treatment": self.treatment,
            "config": self.config,
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config_record, f, indent=2, ensure_ascii=False)

        # Prepare environment variables
        env_vars = {}

        weather = self.config.get("weather")
        if weather:
            env_vars["GAWORLD_WEATHER_TYPE"] = weather["type"]
            env_vars["GAWORLD_WEATHER_START_DAY"] = str(weather["start_day"])
            env_vars["GAWORLD_WEATHER_END_DAY"] = str(weather["end_day"])
            env_vars["GAWORLD_WEATHER_HOURS"] = ",".join(map(str, weather["hours"]))

        env_vars["GAWORLD_TRANSIT_PRICE_MULT"] = str(self.config["transit_price_multiplier"])
        env_vars["GAWORLD_CAR_RESTRICTION"] = str(self.config["car_restriction"]).lower()
        env_vars["GAWORLD_RUSH_HOUR_MULT"] = str(self.config["rush_hour_multiplier"])

        return self.run_simulation(
            days=self.default_days,
            seed=self.default_seed,
            env_vars=env_vars
        )

    def analyze(self) -> Dict[str, Any]:
        """Analyze transport behavior results."""
        state_file = self.experiment_dir / "state" / "agent_state_history.csv"

        if not state_file.exists():
            return {"error": "State file not found", "path": str(state_file)}

        df = pd.read_csv(state_file)

        results = {
            "treatment": self.treatment,
            "n_agents": int(df["agent_id"].nunique()),
            "n_days": int(df["day"].nunique())
        }

        # Extract transport mode from activity (simplified)
        transport_modes = ["公交", "地铁", "出租", "步行", "自驾", "自行车"]
        mode_counts = {}

        for mode in transport_modes:
            count = df["activity"].str.contains(mode, na=False).sum()
            mode_counts[mode] = int(count)

        total_activities = sum(mode_counts.values())
        mode_shares = {
            mode: count / total_activities if total_activities > 0 else 0
            for mode, count in mode_counts.items()
        }

        results["transport_mode_counts"] = mode_counts
        results["transport_mode_shares"] = mode_shares

        # Daily travel cost analysis
        if "daily_travel_cost" in df.columns:
            daily_cost = df.groupby("day")["daily_travel_cost"].agg(["mean", "std"]).to_dict()
            results["daily_travel_cost"] = daily_cost

            # Rush hour analysis
            df["hour"] = df["time"].apply(lambda x: int(x.split(":")[0]) if ":" in str(x) else 0)
            df["is_rush_hour"] = df["hour"].isin([7, 8, 9, 17, 18, 19])

            rush_cost = df[df["is_rush_hour"]]["daily_travel_cost"].mean()
            non_rush_cost = df[~df["is_rush_hour"]]["daily_travel_cost"].mean()

            results["rush_hour_travel_cost"] = float(rush_cost) if not pd.isna(rush_cost) else None
            results["non_rush_hour_travel_cost"] = float(non_rush_cost) if not pd.isna(non_rush_cost) else None

        # Weather impact analysis
        if self.config.get("weather"):
            weather = self.config["weather"]
            start_day = weather["start_day"]
            end_day = weather["end_day"]

            df["is_weather_event"] = (df["day"] >= start_day) & (df["day"] <= end_day)

            weather_cost = df[df["is_weather_event"]]["daily_travel_cost"].mean() if "daily_travel_cost" in df.columns else None
            non_weather_cost = df[~df["is_weather_event"]]["daily_travel_cost"].mean() if "daily_travel_cost" in df.columns else None

            results["weather_impact"] = {
                "weather_period_cost": float(weather_cost) if not pd.isna(weather_cost) else None,
                "non_weather_period_cost": float(non_weather_cost) if not pd.isna(non_weather_cost) else None,
                "weather_premium": float(weather_cost - non_weather_cost) if weather_cost and non_weather_cost else None
            }

        return results


def run_treatment(treatment: str, days: int, seed: int) -> bool:
    """Run a single treatment."""
    exp = ExpTransportBehavior(treatment=treatment, days=days, seed=seed)
    return exp.run()


def analyze_treatment(treatment: str) -> Dict[str, Any]:
    """Analyze a single treatment."""
    exp = ExpTransportBehavior(treatment=treatment)
    return exp.analyze()


def compare_treatments() -> Dict[str, Any]:
    """Compare all treatments."""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = RESULTS_DIR / "exp_transport_behavior" / treatment
        if exp_dir.exists():
            exp = ExpTransportBehavior(treatment=treatment)
            results[treatment] = exp.analyze()

    print("\n=== Transport Behavior Experiment Comparison ===\n")
    print(f"{'Treatment':<25} {'Bus Share':<12} {'Metro Share':<12} {'Avg Cost':<12}")
    print("-" * 60)
    for treatment, res in results.items():
        if "error" not in res:
            shares = res.get("transport_mode_shares", {})
            bus = shares.get("公交", 0) or 0
            metro = shares.get("地铁", 0) or 0
            cost = res.get("daily_travel_cost", {}).get("mean", {}).get(0, 0) or 0
            print(f"{treatment:<25} {bus:<12.4f} {metro:<12.4f} {cost:<12.2f}")

    comparison_file = RESULTS_DIR / "exp_transport_behavior" / "comparison_results.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    return results


def main():
    parser = argparse.ArgumentParser(description="Transport Behavior Experiment (EXP-TRANS-001)")
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