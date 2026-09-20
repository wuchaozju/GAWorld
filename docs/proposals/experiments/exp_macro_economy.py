#!/usr/bin/env python3
"""
GAWorld Experiment: Macro Economy (EXP-ECON-001)

Studies how macroeconomic cycles affect resident wellbeing.

Usage:
    python exp_macro_economy.py run --days 150 --seed 42
    python exp_macro_economy.py analyze
    python exp_macro_economy.py report --days 150 --seed 42
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_experiment import ExperimentRunner, RESULTS_DIR


class ExpMacroEconomy(ExperimentRunner):
    """Macro economy experiment runner."""

    def __init__(self, days: int = 150, seed: int = 42):
        exp_name = "exp_macro_economy"
        exp_dir = RESULTS_DIR / exp_name / f"run_{seed}"

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.run_id = f"run_{seed}"

    def run(self) -> bool:
        """Run the macro economy experiment."""
        config = {
            "experiment": "macro_economy_wellbeing",
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

    def analyze(self, seed: int = 42) -> Dict[str, Any]:
        """Analyze macro economy effects on wellbeing."""
        exp_dir = RESULTS_DIR / "exp_macro_economy" / f"run_{seed}"
        economy_dir = exp_dir / "economy"

        if not economy_dir.exists():
            return {"error": "Economy directory not found"}

        results = {}

        # Load macro state
        macro_state_file = economy_dir / "macro_state.json"
        if macro_state_file.exists():
            with open(macro_state_file) as f:
                results["macro_state"] = json.load(f)

        # Load daily ledger
        ledger_file = economy_dir / "daily_ledger.csv"
        if ledger_file.exists():
            ledger_df = pd.read_csv(ledger_file)
            results["ledger_available"] = True
            results["n_ledger_entries"] = len(ledger_df)

            if "income" in ledger_df.columns:
                results["avg_income"] = float(ledger_df["income"].mean())
                results["income_by_phase"] = self._aggregate_by_macro_phase(ledger_df, "income")

        # Load state history
        state_file = exp_dir / "state" / "agent_state_history.csv"
        if state_file.exists():
            state_df = pd.read_csv(state_file)
            results["n_agents"] = int(state_df["agent_id"].nunique())

            # Compute wellbeing by macro phase (assuming 30-day phases)
            state_df["macro_phase"] = (state_df["day"] - 1) // 30 + 1

            wellbeing_metrics = ["emotion", "stress", "econ_security"]
            wellbeing_by_phase = {}

            for metric in wellbeing_metrics:
                if metric in state_df.columns:
                    phase_agg = state_df.groupby("macro_phase")[metric].agg(["mean", "std"]).to_dict()
                    wellbeing_by_phase[metric] = phase_agg

            results["wellbeing_by_phase"] = wellbeing_by_phase

            # Income quartile analysis
            if "income" in state_df.columns:
                state_df["income_quartile"] = pd.qcut(
                    state_df.groupby("agent_id")["income"].transform("mean"),
                    q=4, labels=["Q1", "Q2", "Q3", "Q4"],
                    duplicates="drop"
                )

                quartile_by_phase = state_df.groupby(["macro_phase", "income_quartile"]).agg({
                    "econ_security": "mean",
                    "stress": "mean",
                    "emotion": "mean"
                })
                results["quartile_by_phase"] = quartile_by_phase.to_dict()

        # Save analysis
        analysis_file = exp_dir / "wellbeing_analysis.json"
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)

        return results

    def _aggregate_by_macro_phase(self, df: pd.DataFrame, column: str) -> Dict:
        """Aggregate a column by macro phase."""
        df = df.copy()
        df["macro_phase"] = (df["day"] - 1) // 30 + 1

        if column not in df.columns:
            return {}

        phase_agg = df.groupby("macro_phase")[column].agg(["mean", "std"]).to_dict()
        return phase_agg


def run_simulation(days: int, seed: int) -> bool:
    """Run macro economy simulation."""
    exp = ExpMacroEconomy(days=days, seed=seed)
    return exp.run()


def analyze_results(seed: int) -> Dict[str, Any]:
    """Analyze simulation results."""
    exp = ExpMacroEconomy()
    return exp.analyze(seed=seed)


def generate_report(days: int, seed: int) -> str:
    """Generate analysis report."""
    exp_dir = RESULTS_DIR / "exp_macro_economy" / f"run_{seed}"

    state_file = exp_dir / "state" / "agent_state_history.csv"
    ledger_file = exp_dir / "economy" / "daily_ledger.csv"

    if not state_file.exists() or not ledger_file.exists():
        return "Error: Simulation data not found"

    state_df = pd.read_csv(state_file)
    ledger_df = pd.read_csv(ledger_file)

    state_df["macro_phase"] = (state_df["day"] - 1) // 30 + 1

    lines = []
    lines.append("# 宏观经济周期与居民福祉分析报告\n")
    lines.append(f"实验配置：{days}天仿真，seed={seed}\n")
    lines.append("\n## 宏观阶段对居民福祉的影响\n")
    lines.append("| 阶段 | 平均情绪 | 平均压力 | 平均经济安全 |\n")
    lines.append("|------|---------|---------|------------|\n")

    for phase in range(1, 6):
        phase_data = state_df[(state_df["day"] >= (phase - 1) * 30 + 1) & (state_df["day"] <= phase * 30)]
        if len(phase_data) > 0:
            lines.append(
                f"| {phase} | {phase_data['emotion'].mean():.3f} "
                f"| {phase_data['stress'].mean():.3f} "
                f"| {phase_data['econ_security'].mean():.3f} |\n"
            )

    report_text = "".join(lines)

    report_file = exp_dir / "wellbeing_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    return report_text


def main():
    parser = argparse.ArgumentParser(description="Macro Economy Experiment (EXP-ECON-001)")
    parser.add_argument("action", choices=["run", "analyze", "report"], help="Action to perform")
    parser.add_argument("--days", type=int, default=150, help="Simulation days (recommended >= 120 for full cycle)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    if args.action == "run":
        success = run_simulation(args.days, args.seed)
        sys.exit(0 if success else 1)
    elif args.action == "analyze":
        results = analyze_results(args.seed)
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    elif args.action == "report":
        report = generate_report(args.days, args.seed)
        print(report)


if __name__ == "__main__":
    main()