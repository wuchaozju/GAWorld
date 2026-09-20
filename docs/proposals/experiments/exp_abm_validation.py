#!/usr/bin/env python3
"""
GAWorld Experiment: ABM Validation (EXP-VAL-001)

Validation framework for comparing simulation outputs against real-world data.

Usage:
    python exp_abm_validation.py run --days 30 --seed 42
    python exp_abm_validation.py validate --metric transport_mode
    python exp_abm_validation.py report
"""

import argparse
import json
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


# Reference benchmarks (representative values, should be updated with real data)
REFERENCE_BENCHMARKS = {
    "transport_mode_share": {
        "bus": 0.25,
        "metro": 0.35,
        "taxi": 0.10,
        "car": 0.20,
        "bike_walk": 0.10
    },
    "engels_coefficient": {
        "low_income": 0.48,
        "middle_income": 0.35,
        "high_income": 0.22
    },
    "savings_rate": {
        "low_income": 0.05,
        "middle_income": 0.20,
        "high_income": 0.35
    },
    "emotion_distribution": {
        "mean": 0.60,
        "std": 0.15
    },
    "commute_time_minutes": {
        "mean": 45,
        "std": 20
    }
}


class ExpABMValidation(ExperimentRunner):
    """ABM validation experiment runner."""

    def __init__(self, days: int = 30, seed: int = 42):
        exp_name = "exp_abm_validation"
        exp_dir = RESULTS_DIR / exp_name / "simulation_output"

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)

    def run(self) -> bool:
        """Run simulation for validation."""
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        config = {
            "experiment": "abm_validation",
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return self.run_simulation(
            days=self.default_days,
            seed=self.default_seed
        )

    def _load_state_long(self) -> pd.DataFrame:
        """Load state history CSV and pivot to wide format."""
        state_file = self.experiment_dir / "state" / "agent_state_history.csv"
        if not state_file.exists():
            return pd.DataFrame()
        df = pd.read_csv(state_file)
        df_wide = df.pivot_table(index=["agent_id", "step"], columns="metric", values="value")
        df_wide = df_wide.reset_index()
        return df_wide

    def extract_transport_mode_data(self) -> Dict[str, float]:
        """Extract transport mode share from agent environment logs."""
        env_dir = self.experiment_dir / "environment"
        if not env_dir.exists():
            return {}

        mode_counts = {
            "bus": 0, "metro": 0, "taxi": 0,
            "car": 0, "bike_walk": 0, "other": 0
        }

        for log_file in env_dir.glob("agent_*.log"):
            try:
                content = log_file.read_text(encoding="utf-8")
            except Exception:
                continue

            for line in content.split("\n"):
                line_lower = line.lower()
                if "公交" in line or "bus" in line_lower:
                    mode_counts["bus"] += 1
                elif "地铁" in line or "metro" in line_lower:
                    mode_counts["metro"] += 1
                elif "出租" in line or "taxi" in line_lower or "打车" in line:
                    mode_counts["taxi"] += 1
                elif "自驾" in line or "开车" in line or "car" in line_lower:
                    mode_counts["car"] += 1
                elif any(k in line for k in ["步行", "自行车", "walk", "bike", "骑行"]):
                    mode_counts["bike_walk"] += 1

        total = sum(mode_counts.values())
        if total == 0:
            return {}
        return {k: v / total for k, v in mode_counts.items()}

    def extract_engels_data(self) -> Dict[str, float]:
        """Extract Engels coefficient data from daily ledger."""
        economy_dir = self.experiment_dir / "economy"
        if not economy_dir.exists():
            return {}

        ledger_file = economy_dir / "daily_ledger.csv"
        if not ledger_file.exists():
            return {}

        df = pd.read_csv(ledger_file)

        if "engel_coefficient" in df.columns:
            return {
                "mean_engels": float(df["engel_coefficient"].mean()),
                "std_engels": float(df["engel_coefficient"].std())
            }
        if "food_expense" in df.columns and "total_consumption" in df.columns:
            df = df.copy()
            df["engels"] = df["food_expense"] / df["total_consumption"]
            return {
                "mean_engels": float(df["engels"].mean()),
                "std_engels": float(df["engels"].std())
            }

        return {}

    def extract_savings_data(self) -> Dict[str, float]:
        """Extract savings rate data."""
        economy_dir = self.experiment_dir / "economy"
        if not economy_dir.exists():
            return {}

        ledger_file = economy_dir / "daily_ledger.csv"
        if not ledger_file.exists():
            return {}

        df = pd.read_csv(ledger_file)

        if "savings" in df.columns and "income" in df.columns:
            savings_rate = (df["savings"] / df["income"]).mean()
            return {"mean_savings_rate": float(savings_rate)}

        return {}

    def extract_emotion_data(self) -> Dict[str, float]:
        """Extract emotion distribution data from state history (long format)."""
        state_file = self.experiment_dir / "state" / "agent_state_history.csv"
        if not state_file.exists():
            return {}

        df = pd.read_csv(state_file)
        emotion_rows = df[df["metric"] == "emotion"]

        if len(emotion_rows) == 0:
            return {}

        return {
            "mean": float(emotion_rows["value"].mean()),
            "std": float(emotion_rows["value"].std()),
            "min": float(emotion_rows["value"].min()),
            "max": float(emotion_rows["value"].max())
        }

    def compute_kl_divergence(self, p: Dict[str, float], q: Dict[str, float]) -> float:
        """Compute KL divergence D(P||Q)."""
        total = 0
        for key in p:
            if key in q and q[key] > 0 and p[key] > 0:
                total += p[key] * np.log(p[key] / q[key])
        return total

    def compute_wasserstein_distance(self, sim_dist: Dict[str, float], ref_dist: Dict[str, float]) -> float:
        """Compute simplified Wasserstein distance."""
        all_keys = set(sim_dist.keys()) | set(ref_dist.keys())
        p_vals = [sim_dist.get(k, 0) for k in all_keys]
        q_vals = [ref_dist.get(k, 0) for k in all_keys]
        return float(np.sqrt(sum((a - b) ** 2 for a, b in zip(p_vals, q_vals))))

    def compute_relative_error(self, sim_value: float, ref_value: float) -> float:
        """Compute relative error."""
        if ref_value == 0:
            return float('inf')
        return abs(sim_value - ref_value) / abs(ref_value)

    def validate_metric(self, metric_name: str) -> Dict[str, Any]:
        """Validate a specific metric."""
        validators = {
            "transport_mode": (self.extract_transport_mode_data, "transport_mode_share", "KL_divergence"),
            "engels_coefficient": (self.extract_engels_data, "engels_coefficient", "relative_error"),
            "savings_rate": (self.extract_savings_data, "savings_rate", "relative_error"),
            "emotion_distribution": (self.extract_emotion_data, "emotion_distribution", "wasserstein_distance")
        }

        if metric_name not in validators:
            return {"error": f"Unknown metric: {metric_name}"}

        extractor, ref_key, error_metric = validators[metric_name]

        sim_data = extractor()
        reference = REFERENCE_BENCHMARKS.get(ref_key, {})

        if not sim_data:
            return {"error": "Could not extract simulation data"}

        # Compute error
        if error_metric == "KL_divergence":
            error = self.compute_kl_divergence(sim_data, reference)
            error_type = "KL divergence"
        elif error_metric == "relative_error":
            sim_value = sim_data.get("mean_engels") or sim_data.get("mean_savings_rate")
            ref_value = list(reference.values())[0] if reference else None
            error = self.compute_relative_error(sim_value, ref_value) if sim_value and ref_value else None
            error_type = "relative error"
        elif error_metric == "wasserstein_distance":
            error = self.compute_wasserstein_distance(sim_data, reference)
            error_type = "Wasserstein distance"
        else:
            error = None
            error_type = "unknown"

        return {
            "metric": metric_name,
            "simulation_data": sim_data,
            "reference_data": reference,
            "error": error,
            "error_type": error_type
        }

    def validate_all(self) -> Dict[str, Any]:
        """Run full validation."""
        results = {}
        for metric in ["transport_mode", "engels_coefficient", "savings_rate", "emotion_distribution"]:
            print(f"[EXP] Validating {metric}...")
            results[metric] = self.validate_metric(metric)
        return results

    def generate_report(self) -> str:
        """Generate validation report."""
        results = self.validate_all()

        lines = []
        lines.append("# ABM 验证报告\n")
        lines.append(f"生成时间：{datetime.now().isoformat()}\n")
        lines.append("\n## 验证结果摘要\n")

        for metric_name, result in results.items():
            if "error" in result:
                lines.append(f"\n### {metric_name}: ERROR - {result['error']}\n")
                continue

            lines.append(f"\n### {metric_name}\n")
            lines.append(f"- 误差类型：{result['error_type']}\n")
            lines.append(f"- 误差值：{result['error']:.4f}\n" if result['error'] else "- 误差值：N/A\n")

            lines.append("\n对比：\n")
            lines.append("| 维度 | 仿真值 | 参考值 | 差异 |\n")
            lines.append("|------|--------|--------|------|\n")

            sim_data = result.get("simulation_data", {})
            ref_data = result.get("reference_data", {})

            if isinstance(sim_data, dict) and isinstance(ref_data, dict):
                all_keys = set(sim_data.keys()) | set(ref_data.keys())
                for key in sorted(all_keys):
                    sim_val = sim_data.get(key, "N/A")
                    ref_val = ref_data.get(key, "N/A")
                    if isinstance(sim_val, (int, float)) and isinstance(ref_val, (int, float)):
                        diff = sim_val - ref_val
                        diff_sign = "+" if diff > 0 else ""
                        lines.append(f"| {key} | {sim_val:.4f} | {ref_val:.4f} | {diff_sign}{diff:.4f} |\n")
                    else:
                        lines.append(f"| {key} | {sim_val} | {ref_val} | - |\n")

        report_text = "".join(lines)

        report_dir = RESULTS_DIR / "exp_abm_validation" / "validation_reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        with open(report_dir / "validation_report.md", "w", encoding="utf-8") as f:
            f.write(report_text)

        return report_text


def run_simulation(days: int, seed: int) -> bool:
    """Run simulation for validation."""
    exp = ExpABMValidation(days=days, seed=seed)
    return exp.run()


def validate_metric(metric: str) -> Dict[str, Any]:
    """Validate a specific metric."""
    exp = ExpABMValidation()
    return exp.validate_metric(metric)


def generate_validation_report() -> str:
    """Generate full validation report."""
    exp = ExpABMValidation()
    return exp.generate_report()


def main():
    parser = argparse.ArgumentParser(description="ABM Validation Experiment (EXP-VAL-001)")
    parser.add_argument("action", choices=["run", "validate", "report"], help="Action to perform")
    parser.add_argument("--metric", help="Specific metric to validate")
    parser.add_argument("--days", type=int, default=30, help="Simulation days")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    if args.action == "run":
        success = run_simulation(args.days, args.seed)
        sys.exit(0 if success else 1)
    elif args.action == "validate":
        if args.metric:
            results = validate_metric(args.metric)
        else:
            exp = ExpABMValidation()
            results = exp.validate_all()
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    elif args.action == "report":
        report = generate_validation_report()
        print(report)


if __name__ == "__main__":
    main()