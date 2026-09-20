#!/usr/bin/env python3
"""
GAWorld Experiment: Policy Framework (EXP-POLICY-001)

Policy event comparison framework for evaluating policy impacts.

Usage:
    python exp_policy_framework.py run --policy traffic_restriction --days 14 --seed 42
    python exp_policy_framework.py analyze --policy traffic_restriction
    python exp_policy_framework.py compare
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

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


POLICY_CONFIGS = {
    "traffic_restriction": {
        "event_name": "临时交通限行",
        "event_description": "主干道限行导致通勤时间上升并影响出行决策",
        "event_day": 3,
        "event_time": "09:00",
        "category": "transport",
        "expected_effects": {
            "behavior": ["出行方式变化", "通勤时间增加"],
            "subjective": ["stress增加", "econ_security下降"]
        }
    },
    "housing_subsidy": {
        "event_name": "住房补贴政策",
        "event_description": "首次购房者可申请每月2000元补贴，持续6个月",
        "event_day": 3,
        "event_time": "08:00",
        "category": "housing",
        "expected_effects": {
            "behavior": ["购房意愿增加", "消费结构变化"],
            "subjective": ["econ_security提升", "emotion改善"]
        }
    },
    "medical_reform": {
        "event_name": "医疗报销比例上调",
        "event_description": "门诊报销比例从50%提升至70%，减轻医疗负担",
        "event_day": 3,
        "event_time": "08:00",
        "category": "social",
        "expected_effects": {
            "behavior": ["就医频率增加", "健康投入上升"],
            "subjective": ["stress下降", "econ_security提升"]
        }
    },
    "job_training": {
        "event_name": "职业技能培训补贴",
        "event_description": "失业人员参加培训可获得每月1500元生活补贴",
        "event_day": 3,
        "event_time": "08:00",
        "category": "employment",
        "expected_effects": {
            "behavior": ["参训率上升", "就业恢复加速"],
            "subjective": ["emotion改善", "stress下降"]
        }
    }
}


class ExpPolicyFramework(ExperimentRunner):
    """Policy framework experiment runner."""

    def __init__(self, policy: str = "traffic_restriction", days: int = 14, seed: int = 42):
        exp_name = "exp_policy_framework"
        exp_dir = RESULTS_DIR / exp_name / policy

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.policy = policy
        self.config = POLICY_CONFIGS.get(policy, POLICY_CONFIGS["traffic_restriction"])

    def run(self) -> bool:
        """Run the policy experiment using compare-event."""
        config_record = {
            "policy": self.policy,
            "config": self.config,
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config_record, f, indent=2, ensure_ascii=False)

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "generative_city_sim.py"),
            "compare-event",
            "--event-name", self.config["event_name"],
            "--event-description", self.config["event_description"],
            "--event-day", str(self.config["event_day"]),
            "--event-time", self.config["event_time"],
            "--sim-days", str(self.default_days),
            "--seed", str(self.default_seed)
        ]

        print(f"[EXP] Running policy experiment: {self.policy}")
        print(f"[EXP] Command: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))

        if result.returncode != 0:
            print(f"[ERROR] {result.stderr}", file=sys.stderr)
            return False

        return True

    def analyze(self) -> Dict[str, Any]:
        """Analyze policy experiment results."""
        comparison_dir = self.experiment_dir / "comparisons"

        if not comparison_dir.exists():
            # Look for alternative result locations
            for subdir in self.experiment_dir.iterdir():
                if subdir.is_dir() and "comparisons" in subdir.name:
                    comparison_dir = subdir
                    break

        if not comparison_dir.exists():
            return {"error": "Comparison results not found", "searched": str(self.experiment_dir)}

        results = {
            "policy": self.policy,
            "config": self.config
        }

        # Look for comparison summary and metrics
        summary_files = list(comparison_dir.glob("**/comparison_summary.md"))
        if summary_files:
            with open(summary_files[0]) as f:
                results["summary_content"] = f.read()

        metrics_files = list(comparison_dir.glob("**/comparison_metrics.csv"))
        if metrics_files:
            metrics_df = pd.read_csv(metrics_files[0])
            results["metrics_available"] = True
            results["n_metrics"] = len(metrics_df)

            if "event_baseline_delta" in metrics_df.columns or "delta" in metrics_df.columns:
                delta_col = "event_baseline_delta" if "event_baseline_delta" in metrics_df.columns else "delta"
                results["avg_delta"] = float(metrics_df[delta_col].mean()) if delta_col in metrics_df.columns else None

        # Load with/without event states for comparison
        with_event_dir = comparison_dir / "with_event"
        without_event_dir = comparison_dir / "without_event"

        if with_event_dir.exists() and without_event_dir.exists():
            with_state = pd.read_csv(with_event_dir / "state" / "agent_state_history.csv")
            without_state = pd.read_csv(without_event_dir / "state" / "agent_state_history.csv")

            subjective_metrics = ["emotion", "stress", "econ_security", "city_identity"]
            effect_summary = {}

            for metric in subjective_metrics:
                if metric in with_state.columns and metric in without_state.columns:
                    with_mean = with_state.groupby("day")[metric].mean()
                    without_mean = without_state.groupby("day")[metric].mean()

                    effect_summary[metric] = {
                        "with_policy_mean": float(with_mean.mean()),
                        "without_policy_mean": float(without_mean.mean()),
                        "avg_effect": float((with_mean - without_mean).mean())
                    }

            results["subjective_effects"] = effect_summary

        return results

    def generate_report(self) -> str:
        """Generate policy experiment report."""
        results = self.analyze()

        lines = []
        lines.append(f"# 政策实验报告：{self.policy}\n")
        lines.append(f"生成时间：{datetime.now().isoformat()}\n")

        if "error" in results:
            lines.append(f"\n[ERROR] {results['error']}\n")
            return "\n".join(lines)

        # Subjective metrics effects
        if "subjective_effects" in results:
            lines.append("## 主观指标变化\n")
            lines.append("| 指标 | 有政策均值 | 无政策均值 | 平均效果 |")
            lines.append("|------|-----------|-----------|---------|")

            for metric, data in results["subjective_effects"].items():
                avg_effect = data["avg_effect"]
                effect_sign = "+" if avg_effect > 0 else ""
                lines.append(
                    f"| {metric} | {data['with_policy_mean']:.3f} "
                    f"| {data['without_policy_mean']:.3f} "
                    f"| {effect_sign}{avg_effect:.3f} |"
                )

        report_text = "\n".join(lines)

        report_file = self.experiment_dir / "policy_report.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_text)

        return report_text


def run_policy(policy: str, days: int, seed: int) -> bool:
    """Run a single policy experiment."""
    exp = ExpPolicyFramework(policy=policy, days=days, seed=seed)
    return exp.run()


def analyze_policy(policy: str) -> Dict[str, Any]:
    """Analyze a single policy experiment."""
    exp = ExpPolicyFramework(policy=policy)
    return exp.analyze()


def compare_policies() -> Dict[str, Any]:
    """Compare all policy experiments."""
    results = {}
    for policy in POLICY_CONFIGS.keys():
        exp_dir = RESULTS_DIR / "exp_policy_framework" / policy
        if exp_dir.exists():
            exp = ExpPolicyFramework(policy=policy)
            results[policy] = exp.analyze()

    print("\n=== Policy Framework Experiment Comparison ===\n")
    print(f"{'Policy':<25} {'Emotion Effect':<15} {'Stress Effect':<15} {'EconSec Effect':<15}")
    print("-" * 70)
    for policy, res in results.items():
        if "error" not in res and "subjective_effects" in res:
            eff = res["subjective_effects"]
            emot = eff.get("emotion", {}).get("avg_effect", 0) or 0
            stres = eff.get("stress", {}).get("avg_effect", 0) or 0
            econ = eff.get("econ_security", {}).get("avg_effect", 0) or 0
            print(f"{policy:<25} {emot:<15.4f} {stres:<15.4f} {econ:<15.4f}")

    comparison_file = RESULTS_DIR / "exp_policy_framework" / "all_policies_comparison.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    return results


def main():
    parser = argparse.ArgumentParser(description="Policy Framework Experiment (EXP-POLICY-001)")
    parser.add_argument("action", choices=["run", "analyze", "report", "compare"], help="Action to perform")
    parser.add_argument("--policy", default="traffic_restriction", help=f"Policy: {', '.join(POLICY_CONFIGS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="Simulation days")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    if args.action == "run":
        success = run_policy(args.policy, args.days, args.seed)
        sys.exit(0 if success else 1)
    elif args.action == "analyze":
        results = analyze_policy(args.policy)
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    elif args.action == "report":
        exp = ExpPolicyFramework(policy=args.policy)
        report = exp.generate_report()
        print(report)
    elif args.action == "compare":
        results = compare_policies()
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()