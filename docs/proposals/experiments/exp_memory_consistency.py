#!/usr/bin/env python3
"""
GAWorld Experiment: Memory Consistency (EXP-MEM-001)

Studies agent behavioral consistency and memory architecture.

Usage:
    python exp_memory_consistency.py run --treatment memory_intact --days 14 --seed 42
    python exp_memory_consistency.py analyze --treatment memory_intact
    python exp_memory_consistency.py compare
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


TREATMENTS = {
    "memory_intact": {
        "reset_between_phases": False,
        "delete_summaries": False,
        "inject_conflict": False,
        "description": "完整记忆运行"
    },
    "memory_reset": {
        "reset_between_phases": True,
        "delete_summaries": False,
        "inject_conflict": False,
        "description": "无记忆运行（reset后重新开始）"
    },
    "memory_selective": {
        "reset_between_phases": False,
        "delete_summaries": True,
        "inject_conflict": False,
        "description": "仅保留 episodic memory"
    },
    "memory_conflict": {
        "reset_between_phases": False,
        "delete_summaries": False,
        "inject_conflict": True,
        "description": "注入冲突记忆"
    }
}


class ExpMemoryConsistency(ExperimentRunner):
    """Memory consistency experiment runner."""

    def __init__(self, treatment: str = "memory_intact", days: int = 14, seed: int = 42):
        exp_name = "exp_memory_consistency"
        exp_dir = RESULTS_DIR / exp_name / treatment

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.treatment = treatment
        self.config = TREATMENTS.get(treatment, TREATMENTS["memory_intact"])

    def run(self) -> bool:
        """Run the memory consistency experiment."""
        import os
        import json

        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        config_record = {
            "treatment": self.treatment,
            "config": self.config,
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config_record, f, indent=2, ensure_ascii=False)

        # Run Phase 1: Day 1-7
        phase1_dir = self.experiment_dir / "phase_1"
        phase1_dir.mkdir(parents=True, exist_ok=True)

        phase1_config = {
            "sim_days": 7,
            "random_seed": self.default_seed,
            "stateful": False,
            "state_output_dir": str(phase1_dir / "state"),
            "network_output_dir": str(phase1_dir / "network"),
            "diary_output_dir": str(phase1_dir / "diaries"),
            "log_dir": str(phase1_dir / "logs"),
            "memory_dir": str(phase1_dir / "memory"),
            "environment_output_dir": str(phase1_dir / "environment"),
            "economy_output_dir": str(phase1_dir / "economy"),
            "external_environment_service": {
                "enabled": False
            }
        }

        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent.parent.parent / "generative_city_sim.py"),
            "run"
        ]

        print(f"[EXP] Running Phase 1: days=7 seed={self.default_seed}")
        env = os.environ.copy()
        env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(phase1_config)
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            print(f"[ERROR] Phase 1 failed: {result.stderr}", file=sys.stderr)
            return False

        # Handle between-phase processing
        if self.config.get("reset_between_phases"):
            print("[EXP] Resetting simulation for Phase 2...")
            subprocess.run(
                [sys.executable, str(Path(__file__).parent.parent.parent.parent / "generative_city_sim.py"), "reset"],
                capture_output=True
            )
        elif self.config.get("delete_summaries"):
            # Delete long-term summaries
            memory_dir = phase1_dir / "memory"
            if memory_dir.exists():
                for mf in memory_dir.glob("agent_*_summary.json"):
                    mf.unlink()
                print(f"[EXP] Deleted summary files from {memory_dir}")

        # Run Phase 2: Day 8-14 (or reset + re-run)
        phase2_dir = self.experiment_dir / "phase_2"
        phase2_dir.mkdir(parents=True, exist_ok=True)

        if self.config.get("inject_conflict"):
            self._inject_conflict_memory()

        phase2_config = {
            "sim_days": 7,
            "random_seed": self.default_seed + 100,
            "stateful": False,
            "state_output_dir": str(phase2_dir / "state"),
            "network_output_dir": str(phase2_dir / "network"),
            "diary_output_dir": str(phase2_dir / "diaries"),
            "log_dir": str(phase2_dir / "logs"),
            "memory_dir": str(phase2_dir / "memory"),
            "environment_output_dir": str(phase2_dir / "environment"),
            "economy_output_dir": str(phase2_dir / "economy"),
            "external_environment_service": {
                "enabled": False
            }
        }

        print(f"[EXP] Running Phase 2: days=7 seed={self.default_seed + 100}")
        env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(phase2_config)
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            print(f"[ERROR] Phase 2 failed: {result.stderr}", file=sys.stderr)
            return False

        return True

    def _inject_conflict_memory(self):
        """Inject conflicting memories to agents."""
        import random
        conflict_agents = random.sample(range(1, 51), 5)

        for agent_id in conflict_agents:
            cmd = [
                sys.executable,
                str(Path(__file__).parent.parent.parent.parent / "generative_city_sim.py"),
                "rag-add",
                "--agent-id", str(agent_id),
                "--text", "最近做了一个重大决定：辞掉工作去旅行一年，这个决定让我感到前所未有的自由和快乐",
                "--timestamp", "Day3 10:00",
                "--source", "experiment_conflict"
            ]
            subprocess.run(cmd, capture_output=True)

        print(f"[EXP] Injected conflict memories to agents: {conflict_agents}")

    def analyze(self) -> Dict[str, Any]:
        """Analyze memory consistency results."""
        phase1_dir = self.experiment_dir / "phase_1"
        phase2_dir = self.experiment_dir / "phase_2"

        results = {"treatment": self.treatment}

        # Analyze Phase 1
        if phase1_dir.exists():
            state_file = phase1_dir / "state" / "agent_state_history.csv"
            if state_file.exists():
                df1 = pd.read_csv(state_file)
                results["phase_1"] = {
                    "n_days": int(df1["day"].nunique()),
                    "n_agents": int(df1["agent_id"].nunique())
                }

                for col in ["emotion", "stress", "econ_security"]:
                    if col in df1.columns:
                        results["phase_1"][f"{col}_mean"] = float(df1[col].mean())

        # Analyze Phase 2
        if phase2_dir.exists():
            state_file = phase2_dir / "state" / "agent_state_history.csv"
            if state_file.exists():
                df2 = pd.read_csv(state_file)
                results["phase_2"] = {
                    "n_days": int(df2["day"].nunique()),
                    "n_agents": int(df2["agent_id"].nunique())
                }

                for col in ["emotion", "stress", "econ_security"]:
                    if col in df2.columns:
                        results["phase_2"][f"{col}_mean"] = float(df2[col].mean())

        # Cross-phase consistency (simplified: compare final state)
        if phase1_dir.exists() and phase2_dir.exists():
            state1 = phase1_dir / "state" / "agent_state_history.csv"
            state2 = phase2_dir / "state" / "agent_state_history.csv"

            if state1.exists() and state2.exists():
                df1 = pd.read_csv(state1)
                df2 = pd.read_csv(state2)

                # Get last day of each phase
                last_day1 = int(df1["day"].max())
                last_day2 = int(df2["day"].max())

                final1 = df1[df1["day"] == last_day1].groupby("agent_id")["emotion"].mean()
                final2 = df2[df2["day"] == last_day2].groupby("agent_id")["emotion"].mean()

                common_agents = final1.index.intersection(final2.index)
                if len(common_agents) > 0:
                    consistency = float(final1.loc[common_agents].corr(final2.loc[common_agents]))
                    results["cross_phase_emotion_consistency"] = consistency

        return results

    def compute_interview_consistency(self, phase: int) -> Dict[str, Any]:
        """Compute consistency from interview responses."""
        interview_dir = self.experiment_dir / f"phase_{phase}_interviews" / "responses.json"

        if not interview_dir.exists():
            return {"error": "Interview file not found"}

        with open(interview_dir) as f:
            responses = json.load(f)

        # Group by agent and question
        agent_responses = {}
        for r in responses:
            key = f"{r['agent_id']}_{r['question']}"
            if key not in agent_responses:
                agent_responses[key] = []
            agent_responses[key].append(r["response"])

        # Compute consistency (simplified: length variance)
        consistencies = {}
        for key, resps in agent_responses.items():
            if len(resps) > 1:
                lengths = [len(r) for r in resps]
                consistencies[key] = 1 - np.std(lengths) / np.mean(lengths) if np.mean(lengths) > 0 else 0

        return {
            "mean_consistency": float(np.mean(list(consistencies.values()))) if consistencies else None,
            "n_comparisons": len(consistencies)
        }


def run_treatment(treatment: str, days: int, seed: int) -> bool:
    """Run a single treatment."""
    exp = ExpMemoryConsistency(treatment=treatment, days=days, seed=seed)
    return exp.run()


def analyze_treatment(treatment: str) -> Dict[str, Any]:
    """Analyze a single treatment."""
    exp = ExpMemoryConsistency(treatment=treatment)
    return exp.analyze()


def compare_treatments() -> Dict[str, Any]:
    """Compare all treatments."""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = RESULTS_DIR / "exp_memory_consistency" / treatment
        if exp_dir.exists():
            exp = ExpMemoryConsistency(treatment=treatment)
            results[treatment] = exp.analyze()

    print("\n=== Memory Consistency Experiment Comparison ===\n")
    print(f"{'Treatment':<20} {'Phase 1 Emotion':<16} {'Phase 2 Emotion':<16} {'Cross Consistency':<18}")
    print("-" * 70)
    for treatment, res in results.items():
        if "error" not in res:
            p1 = res.get("phase_1", {}).get("emotion_mean", 0) or 0
            p2 = res.get("phase_2", {}).get("emotion_mean", 0) or 0
            cross = res.get("cross_phase_emotion_consistency", 0) or 0
            print(f"{treatment:<20} {p1:<16.4f} {p2:<16.4f} {cross:<18.4f}")

    comparison_file = RESULTS_DIR / "exp_memory_consistency" / "comparison_results.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    return results


def main():
    parser = argparse.ArgumentParser(description="Memory Consistency Experiment (EXP-MEM-001)")
    parser.add_argument("action", choices=["run", "analyze", "compare"], help="Action to perform")
    parser.add_argument("--treatment", default="memory_intact", help=f"Treatment: {', '.join(TREATMENTS.keys())}")
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