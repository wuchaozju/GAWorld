#!/usr/bin/env python3
"""
GAWorld Unified Experiment Runner Framework

Provides a common interface for running all 9 experiments with consistent
handling of simulation execution, data collection, and result reporting.

Usage:
    python run_experiment.py --experiment exp_misinfo_spread --action run --treatment control
    python run_experiment.py --experiment exp_polarization --action compare
    python run_experiment.py --list-experiments
"""

import argparse
import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np

# Project root (two levels up from this file)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SIMULATOR_SCRIPT = PROJECT_ROOT / "generative_city_sim.py"
RESULTS_DIR = PROJECT_ROOT / "docs" / "proposals" / "results"

# Ensure results directory exists
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class ExperimentRunner:
    """Base class for running GAWorld experiments."""

    def __init__(
        self,
        experiment_name: str,
        experiment_dir: Path,
        default_days: int = 14,
        default_seed: int = 42
    ):
        self.experiment_name = experiment_name
        self.experiment_dir = experiment_dir
        self.default_days = default_days
        self.default_seed = default_seed
        self.results_dir = RESULTS_DIR / experiment_name
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def run_simulation(
        self,
        days: int,
        seed: int,
        extra_args: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None
    ) -> bool:
        """Run the generative_city_sim.py simulation via subprocess."""
        # Ensure experiment directory exists
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        config_overrides = {
            "agent_ids": [1, 2, 3, 4, 5],
            "sim_days": days,
            "random_seed": seed,
            "state_output_dir": str(self.experiment_dir / "state"),
            "network_output_dir": str(self.experiment_dir / "network"),
            "diary_output_dir": str(self.experiment_dir / "diaries"),
            "log_dir": str(self.experiment_dir / "logs"),
            "memory_dir": str(self.experiment_dir / "memory"),
            "environment_output_dir": str(self.experiment_dir / "environment"),
            "economy_output_dir": str(self.experiment_dir / "economy"),
            "intervention": {
                "enabled": True,
                "output_dir": str(self.experiment_dir / "intervention"),
            },
        }

        cmd = [
            sys.executable,
            str(SIMULATOR_SCRIPT),
            "run"
        ]

        if extra_args:
            cmd.extend(extra_args)

        print(f"[RUNNER] Executing: {' '.join(cmd)}")
        print(f"[RUNNER] Output directory: {self.experiment_dir}")

        # Merge environment variables and add config overrides
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        import json
        env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(config_overrides)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(PROJECT_ROOT)
        )

        if result.returncode != 0:
            print(f"[RUNNER] ERROR: Simulation failed", file=sys.stderr)
            print(f"[RUNNER] STDERR: {result.stderr[:2000]}", file=sys.stderr)
            return False

        print(f"[RUNNER] Simulation completed successfully")
        return True

    def load_state_history(self) -> Optional[pd.DataFrame]:
        """Load agent state history from simulation output."""
        state_file = self.experiment_dir / "state" / "agent_state_history.csv"
        if not state_file.exists():
            return None
        return pd.read_csv(state_file)

    def load_economy_data(self) -> Optional[Dict[str, pd.DataFrame]]:
        """Load economy module outputs."""
        economy_dir = self.experiment_dir / "economy"
        if not economy_dir.exists():
            return None

        data = {}
        for f in economy_dir.glob("*.csv"):
            data[f.stem] = pd.read_csv(f)

        macro_state_file = economy_dir / "macro_state.json"
        if macro_state_file.exists():
            with open(macro_state_file) as f:
                data["macro_state"] = json.load(f)

        return data

    def compute_basic_statistics(self) -> Dict[str, Any]:
        """Compute basic statistics from simulation output."""
        stats = {}
        state_df = self.load_state_history()

        if state_df is not None:
            stats["n_agents"] = state_df["agent_id"].nunique()
            stats["n_days"] = state_df["day"].nunique()
            stats["days_run"] = sorted(state_df["day"].unique().tolist())

            for col in ["emotion", "stress", "econ_security"]:
                if col in state_df.columns:
                    stats[f"{col}_mean"] = state_df[col].mean()
                    stats[f"{col}_std"] = state_df[col].std()

        economy_data = self.load_economy_data()
        if economy_data:
            stats["economy_modules"] = list(economy_data.keys())

        return stats

    def save_results_json(self, data: Dict[str, Any], filename: str):
        """Save results to JSON file."""
        output_file = self.results_dir / filename
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"[RUNNER] Saved results to {output_file}")

    def save_results_csv(self, df: pd.DataFrame, filename: str):
        """Save results to CSV file."""
        output_file = self.results_dir / filename
        df.to_csv(output_file, index=False)
        print(f"[RUNNER] Saved CSV to {output_file}")

    def generate_summary_report(self) -> str:
        """Generate a text summary of experiment results."""
        stats = self.compute_basic_statistics()

        lines = []
        lines.append(f"# {self.experiment_name} Experiment Summary")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append(f"Output directory: {self.experiment_dir}")
        lines.append("")
        lines.append("## Basic Statistics")
        lines.append(f"- Agents: {stats.get('n_agents', 'N/A')}")
        lines.append(f"- Days run: {stats.get('n_days', 'N/A')}")
        lines.append(f"- Days: {stats.get('days_run', 'N/A')}")

        for key in ["emotion", "stress", "econ_security"]:
            mean_key = f"{key}_mean"
            std_key = f"{key}_std"
            if mean_key in stats:
                lines.append(
                    f"- {key}: {stats[mean_key]:.4f} ± {stats.get(std_key, 0):.4f}"
                )

        return "\n".join(lines)


class ExperimentRegistry:
    """Registry of all available experiments."""

    _experiments = {
        "exp_misinfo_spread": {
            "proposal": "EXP-INFO-001_misinfo_spread.md",
            "description": "Misinformation spread in social networks",
            "class": "ExpMisinfoSpread",
            "module": "exp_misinfo_spread",
            "treatments": ["control", "treatment_a", "treatment_b"],
            "default_days": 7,
        },
        "exp_polarization": {
            "proposal": "EXP-POL-001_polarization.md",
            "description": "Opinion polarization and echo chambers",
            "class": "ExpPolarization",
            "module": "exp_polarization",
            "treatments": ["control_baseline", "treatment_diversity", "treatment_filter", "treatment_social"],
            "default_days": 14,
        },
        "exp_macro_economy": {
            "proposal": "EXP-ECON-001_macro_economy.md",
            "description": "Macro economy cycles and wellbeing",
            "class": "ExpMacroEconomy",
            "module": "exp_macro_economy",
            "treatments": ["all_agents"],
            "default_days": 150,
        },
        "exp_emotion_contagion": {
            "proposal": "EXP-EMO-001_emotion_contagion.md",
            "description": "Emotion contagion in social networks",
            "class": "ExpEmotionContagion",
            "module": "exp_emotion_contagion",
            "treatments": ["control", "treatment_happy", "treatment_sad", "treatment_sparse"],
            "default_days": 14,
        },
        "exp_memory_consistency": {
            "proposal": "EXP-MEM-001_memory_consistency.md",
            "description": "Agent behavior consistency and memory",
            "class": "ExpMemoryConsistency",
            "module": "exp_memory_consistency",
            "treatments": ["memory_intact", "memory_reset", "memory_selective", "memory_conflict"],
            "default_days": 14,
        },
        "exp_network_evolution": {
            "proposal": "EXP-NET-001_network_evolution.md",
            "description": "Social network evolution and community structure",
            "class": "ExpNetworkEvolution",
            "module": "exp_network_evolution",
            "treatments": ["natural_evolution", "homophily_boost", "event_disruption", "bridge_creation"],
            "default_days": 30,
        },
        "exp_policy_framework": {
            "proposal": "EXP-POLICY-001_policy_framework.md",
            "description": "Policy event comparison framework",
            "class": "ExpPolicyFramework",
            "module": "exp_policy_framework",
            "treatments": ["traffic_restriction", "housing_subsidy", "medical_reform", "job_training"],
            "default_days": 14,
        },
        "exp_transport_behavior": {
            "proposal": "EXP-TRANS-001_transport_behavior.md",
            "description": "Transport behavior and policy",
            "class": "ExpTransportBehavior",
            "module": "exp_transport_behavior",
            "treatments": ["control", "treatment_weather_rain", "treatment_weather_hot", "treatment_transit_price", "treatment_car_restriction", "treatment_rush_hour_cost"],
            "default_days": 14,
        },
        "exp_abm_validation": {
            "proposal": "EXP-VAL-001_abm_validation.md",
            "description": "ABM validation framework",
            "class": "ExpABMValidation",
            "module": "exp_abm_validation",
            "treatments": ["full_validation"],
            "default_days": 30,
        },
    }

    @classmethod
    def list_experiments(cls) -> List[str]:
        """Return list of available experiment names."""
        return list(cls._experiments.keys())

    @classmethod
    def get_experiment_info(cls, name: str) -> Optional[Dict]:
        """Get information about a specific experiment."""
        return cls._experiments.get(name)

    @classmethod
    def get_all_treatments(cls, name: str) -> List[str]:
        """Get all treatments for an experiment."""
        info = cls._experiments.get(name, {})
        return info.get("treatments", [])

    @classmethod
    def get_default_days(cls, name: str) -> int:
        """Get default days for an experiment."""
        info = cls._experiments.get(name, {})
        return info.get("default_days", 14)


def list_experiments():
    """Print list of all available experiments."""
    print("\nAvailable Experiments:")
    print("-" * 80)
    for name, info in ExperimentRegistry._experiments.items():
        treatments = ", ".join(info["treatments"])
        print(f"\n{name}")
        print(f"  Description: {info['description']}")
        print(f"  Proposal: {info['proposal']}")
        print(f"  Treatments: {treatments}")
        print(f"  Default days: {info['default_days']}")
    print()


def run_single_experiment(
    experiment_name: str,
    treatment: str,
    days: int,
    seed: int,
    **kwargs
) -> bool:
    """Run a single experiment treatment."""
    # Import the experiment module dynamically
    info = ExperimentRegistry.get_experiment_info(experiment_name)
    if not info:
        print(f"[ERROR] Unknown experiment: {experiment_name}")
        return False

    module_name = info["module"]
    class_name = info["class"]

    try:
        module = __import__(module_name, fromlist=[class_name])
        exp_class = getattr(module, class_name)
        exp_instance = exp_class(treatment=treatment, days=days, seed=seed)
        return exp_instance.run()
    except Exception as e:
        print(f"[ERROR] Failed to run experiment: {e}")
        import traceback
        traceback.print_exc()
        return False


def analyze_experiment(
    experiment_name: str,
    treatment: str,
    **kwargs
) -> Dict[str, Any]:
    """Analyze results from an experiment."""
    info = ExperimentRegistry.get_experiment_info(experiment_name)
    if not info:
        return {"error": f"Unknown experiment: {experiment_name}"}

    module_name = info["module"]
    class_name = info["class"]

    try:
        module = __import__(module_name, fromlist=[class_name])
        exp_class = getattr(module, class_name)
        exp_instance = exp_class(treatment=treatment)
        exp_instance.experiment_dir = RESULTS_DIR / experiment_name / treatment
        exp_instance.results_dir = RESULTS_DIR / experiment_name
        return exp_instance.analyze()
    except Exception as e:
        print(f"[ERROR] Failed to analyze experiment: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


def compare_experiments(experiment_name: str) -> Dict[str, Any]:
    """Compare all treatments of an experiment."""
    info = ExperimentRegistry.get_experiment_info(experiment_name)
    if not info:
        return {"error": f"Unknown experiment: {experiment_name}"}

    module_name = info["module"]
    class_name = info["class"]
    treatments = info["treatments"]

    results = {}
    for treatment in treatments:
        result = analyze_experiment(experiment_name, treatment)
        results[treatment] = result

    return results


def main():
    parser = argparse.ArgumentParser(
        description="GAWorld Unified Experiment Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_experiment.py --list-experiments
  python run_experiment.py --experiment exp_misinfo_spread --action run --treatment control
  python run_experiment.py --experiment exp_polarization --action run --treatment treatment_diversity
  python run_experiment.py --experiment exp_polarization --action analyze --treatment control_baseline
  python run_experiment.py --experiment exp_polarization --action compare
        """
    )

    parser.add_argument(
        "--list-experiments",
        action="store_true",
        help="List all available experiments"
    )

    parser.add_argument(
        "--experiment",
        type=str,
        choices=ExperimentRegistry.list_experiments(),
        help="Name of the experiment to run"
    )

    parser.add_argument(
        "--action",
        type=str,
        choices=["run", "analyze", "compare"],
        default="run",
        help="Action to perform"
    )

    parser.add_argument(
        "--treatment",
        type=str,
        help="Treatment to run or analyze"
    )

    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of simulation days"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed"
    )

    args = parser.parse_args()

    if args.list_experiments:
        list_experiments()
        return

    if not args.experiment:
        parser.print_help()
        return

    if args.action == "run":
        if not args.treatment:
            print("[ERROR] --treatment is required for --action run")
            return

        default_days = ExperimentRegistry.get_default_days(args.experiment)
        days = args.days or default_days

        success = run_single_experiment(
            args.experiment,
            args.treatment,
            days,
            args.seed
        )

        if success:
            print(f"[SUCCESS] Experiment {args.experiment} ({args.treatment}) completed")
        else:
            print(f"[FAILED] Experiment {args.experiment} ({args.treatment}) failed")

    elif args.action == "analyze":
        if not args.treatment:
            print("[ERROR] --treatment is required for --action analyze")
            return

        results = analyze_experiment(args.experiment, args.treatment)
        print(json.dumps(results, indent=2, default=str))

    elif args.action == "compare":
        results = compare_experiments(args.experiment)
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()