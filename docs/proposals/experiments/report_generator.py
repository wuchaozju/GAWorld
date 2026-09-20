#!/usr/bin/env python3
"""
GAWorld Experiment Report Generator Template

Generates research reports from experiment outputs with statistics and analysis.

Usage:
    python report_generator.py generate --experiment exp_polarization
    python report_generator.py generate --experiment exp_misinfo_spread --treatment control
    python report_generator.py batch --all
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_experiment import RESULTS_DIR


# Mapping from experiment name to their analysis modules
EXPERIMENT_MODULES = {
    "exp_misinfo_spread": ("exp_misinfo_spread", "ExpMisinfoSpread"),
    "exp_polarization": ("exp_polarization", "ExpPolarization"),
    "exp_macro_economy": ("exp_macro_economy", "ExpMacroEconomy"),
    "exp_emotion_contagion": ("exp_emotion_contagion", "ExpEmotionContagion"),
    "exp_memory_consistency": ("exp_memory_consistency", "ExpMemoryConsistency"),
    "exp_network_evolution": ("exp_network_evolution", "ExpNetworkEvolution"),
    "exp_policy_framework": ("exp_policy_framework", "ExpPolicyFramework"),
    "exp_transport_behavior": ("exp_transport_behavior", "ExpTransportBehavior"),
    "exp_abm_validation": ("exp_abm_validation", "ExpABMValidation"),
}

# Experiment metadata for reports
EXPERIMENT_METADATA = {
    "exp_misinfo_spread": {
        "title": "Information Spread and Misinformation Diffusion",
        "proposal": "EXP-INFO-001",
        "hypotheses": [
            "H1: Social network density positively correlates with misinformation spread speed",
            "H2: High risk preference agents are more likely to spread unverified information",
            "H3: High platform dependence increases susceptibility to misinformation",
            "H4: Cross-viewpoint exposure reduces misinformation acceptance"
        ],
        "key_metrics": ["misinformation_risk", "cross_viewpoint_exposure", "spread_delay"]
    },
    "exp_polarization": {
        "title": "Opinion Polarization and Echo Chamber Effects",
        "proposal": "EXP-POL-001",
        "hypotheses": [
            "H1: Similar agents tend to cluster forming echo chambers",
            "H2: Increased cross-viewpoint exposure reduces polarization",
            "H3: Network homophily accelerates polarization",
            "H4: High policy sensitivity agents are more susceptible to polarization"
        ],
        "key_metrics": ["stance_score", "polarization_index", "cross_viewpoint_exposure"]
    },
    "exp_macro_economy": {
        "title": "Macroeconomic Cycles and Resident Wellbeing",
        "proposal": "EXP-ECON-001",
        "hypotheses": [
            "H1: Macro cycle effects are asymmetric across income levels",
            "H2: Low-income agents experience larger econ_security decline during downturns",
            "H3: Recovery from macro shocks takes 30-90 days",
            "H4: Industry type affects shock sensitivity"
        ],
        "key_metrics": ["emotion", "stress", "econ_security", "income", "savings_rate"]
    },
    "exp_emotion_contagion": {
        "title": "Emotion Contagion and Social Network Dynamics",
        "proposal": "EXP-EMO-001",
        "hypotheses": [
            "H1: Emotions spread positively through social contact",
            "H2: Relationship intimacy increases contagion strength",
            "H3: High-centrality agents serve as emotional bridges",
            "H4: Emotion contagion has cascade effects"
        ],
        "key_metrics": ["emotion", "social_influence", "relationship_strength", "contagion_speed"]
    },
    "exp_memory_consistency": {
        "title": "Agent Behavioral Consistency and Memory Architecture",
        "proposal": "EXP-MEM-001",
        "hypotheses": [
            "H1: Agents with memory show higher behavioral consistency",
            "H2: Richer memory leads to more consistent responses to similar situations",
            "H3: Long-term summaries contribute more to consistency than episodic memory",
            "H4: Conflicting memories cause decision摇摆 and increase behavioral variance"
        ],
        "key_metrics": ["behavioral_consistency", "memory_recall_rate", "decision_stability"]
    },
    "exp_network_evolution": {
        "title": "Social Network Evolution and Community Structure",
        "proposal": "EXP-NET-001",
        "hypotheses": [
            "H1: Similar agents are more likely to form connections (homophily effect)",
            "H2: High network centrality agents are critical for information propagation",
            "H3: Community structure strengthens over simulation days",
            "H4: External events temporarily disrupt existing community structure"
        ],
        "key_metrics": ["network_density", "homophily", "modularity", "betweenness_centrality"]
    },
    "exp_policy_framework": {
        "title": "Policy Event Comparison Framework",
        "proposal": "EXP-POLICY-001",
        "hypotheses": [
            "H1: Policy effects vary by income level and occupation type",
            "H2: Policy effects show temporal decay or amplification",
            "H3: Multi-policy combinations produce non-linear interactions",
            "H4: Policy effects are predictable from intervention metrics"
        ],
        "key_metrics": ["emotion", "stress", "econ_security", "policy_sensitivity"]
    },
    "exp_transport_behavior": {
        "title": "Urban Travel Behavior and Transport Policy",
        "proposal": "EXP-TRANS-001",
        "hypotheses": [
            "H1: Rainy weather reduces open-air transport mode usage",
            "H2: Rush hour reduces taxi usage, increases public transit",
            "H3: Higher income correlates with higher car/taxi usage",
            "H4: Car restriction policies change transport mode structure"
        ],
        "key_metrics": ["transport_mode", "daily_travel_cost", "commute_time"]
    },
    "exp_abm_validation": {
        "title": "ABM Validation Framework",
        "proposal": "EXP-VAL-001",
        "hypotheses": [
            "H1: GAWorld behavioral patterns match real urban data trends",
            "H2: Model errors concentrate in extreme cases",
            "H3: Parameter calibration improves model-real data fit",
            "H4: Different agent types' behavioral patterns are captured by model"
        ],
        "key_metrics": ["KL_divergence", "relative_error", "wasserstein_distance"]
    }
}


class ReportGenerator:
    """Generates research reports from experiment outputs."""

    def __init__(self, experiment_name: str, treatment: Optional[str] = None):
        self.experiment_name = experiment_name
        self.treatment = treatment
        self.metadata = EXPERIMENT_METADATA.get(experiment_name, {})
        self.results_dir = RESULTS_DIR / experiment_name

    def load_experiment_data(self, treatment: str) -> Dict[str, Any]:
        """Load experiment results for a specific treatment."""
        exp_dir = self.results_dir / treatment

        if not exp_dir.exists():
            return {"error": f"Experiment directory not found: {exp_dir}"}

        data = {"treatment": treatment}

        # Load experiment config
        config_file = exp_dir / "experiment_config.json"
        if config_file.exists():
            with open(config_file) as f:
                data["config"] = json.load(f)

        # Load state history if available
        state_file = exp_dir / "state" / "agent_state_history.csv"
        if state_file.exists():
            data["state_history"] = pd.read_csv(state_file)

        # Load comparison results if available
        comparison_file = exp_dir / "comparison_results.json"
        if comparison_file.exists():
            with open(comparison_file) as f:
                data["comparison_results"] = json.load(f)

        return data

    def compute_summary_statistics(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute summary statistics from experiment data."""
        stats = {}

        if "state_history" in data and data["state_history"] is not None:
            df = data["state_history"]

            stats["n_agents"] = int(df["agent_id"].nunique())
            stats["n_days"] = int(df["day"].nunique())

            # Time series metrics
            for col in ["emotion", "stress", "econ_security"]:
                if col in df.columns:
                    daily = df.groupby("day")[col].mean()
                    stats[f"{col}_daily"] = daily.to_dict()
                    stats[f"{col}_overall_mean"] = float(df[col].mean())
                    stats[f"{col}_overall_std"] = float(df[col].std())

            # Daily variability
            daily_vars = df.groupby("day").agg({
                col: "std" for col in ["emotion", "stress", "econ_security"] if col in df.columns
            })
            stats["daily_variability"] = daily_vars.to_dict()

        return stats

    def format_hypothesis_results(self, results: Dict[str, Any]) -> str:
        """Format hypothesis testing results."""
        lines = []

        hypotheses = self.metadata.get("hypotheses", [])
        for i, h in enumerate(hypotheses, 1):
            lines.append(f"**{h}**")
            # TODO: Add actual hypothesis test results when available
            lines.append(f"  - Status: Not yet tested")
            lines.append("")

        return "\n".join(lines)

    def format_key_metrics(self, stats: Dict[str, Any]) -> str:
        """Format key metrics table."""
        key_metrics = self.metadata.get("key_metrics", [])

        lines = []
        lines.append("| Metric | Mean | Std | Min | Max |")
        lines.append("|--------|------|-----|-----|-----|")

        for metric in key_metrics:
            if f"{metric}_overall_mean" in stats:
                mean = stats[f"{metric}_overall_mean"]
                std = stats.get(f"{metric}_overall_std", 0) or 0

                daily_data = stats.get(f"{metric}_daily", {})
                if daily_data:
                    values = list(daily_data.values())
                    min_val = min(values) if values else 0
                    max_val = max(values) if values else 0
                else:
                    min_val = max_val = 0

                lines.append(f"| {metric} | {mean:.4f} | {std:.4f} | {min_val:.4f} | {max_val:.4f} |")

        return "\n".join(lines)

    def generate_markdown_report(
        self,
        treatment: str,
        stats: Dict[str, Any],
        analysis_results: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate a markdown research report."""
        title = self.metadata.get("title", self.experiment_name)
        proposal = self.metadata.get("proposal", "")

        lines = []
        lines.append(f"# {title}")
        lines.append(f"\n**Experiment**: {self.experiment_name}")
        lines.append(f"**Proposal**: {proposal}")
        lines.append(f"**Treatment**: {treatment}")
        lines.append(f"**Generated**: {datetime.now().isoformat()}")
        lines.append("")

        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"Ran simulation for {stats.get('n_days', 'N/A')} days with "
                    f"{stats.get('n_agents', 'N/A')} agents.")
        lines.append("")

        # Hypotheses
        lines.append("## Hypothesis Testing")
        lines.append("")
        lines.append(self.format_hypothesis_results(stats))
        lines.append("")

        # Key Metrics
        lines.append("## Key Metrics")
        lines.append("")
        lines.append(self.format_key_metrics(stats))
        lines.append("")

        # Detailed Analysis
        if analysis_results:
            lines.append("## Detailed Analysis")
            lines.append("")
            if isinstance(analysis_results, dict):
                for key, value in analysis_results.items():
                    if key != "treatment" and key != "config":
                        lines.append(f"### {key}")
                        if isinstance(value, dict):
                            for k, v in value.items():
                                lines.append(f"- {k}: {v}")
                        elif isinstance(value, list):
                            for item in value[:10]:  # Limit output
                                lines.append(f"- {item}")
                        else:
                            lines.append(f"- {value}")
                        lines.append("")
            lines.append("")

        # Temporal Trends
        if "emotion_daily" in stats:
            lines.append("## Temporal Trends")
            lines.append("")
            lines.append("### Emotion Over Time")
            for day, value in list(stats["emotion_daily"].items())[:7]:
                lines.append(f"- Day {day}: {value:.4f}")
            lines.append("")

        # Conclusions
        lines.append("## Conclusions")
        lines.append("")
        lines.append("*[Add your analysis and conclusions here]*")
        lines.append("")

        # References
        lines.append("## References")
        lines.append("")
        lines.append(f"- GAWorld Proposal: {proposal}")
        lines.append("")

        return "\n".join(lines)

    def generate(self, treatment: Optional[str] = None) -> str:
        """Generate report for specified treatment or all treatments."""
        treatment = treatment or self.treatment

        if treatment:
            return self._generate_single_report(treatment)
        else:
            return self._generate_all_report()

    def _generate_single_report(self, treatment: str) -> str:
        """Generate report for a single treatment."""
        data = self.load_experiment_data(treatment)
        if "error" in data:
            return f"Error loading data: {data['error']}"

        stats = self.compute_summary_statistics(data)
        report = self.generate_markdown_report(treatment, stats, data)

        # Save report
        report_dir = self.results_dir / treatment
        report_dir.mkdir(parents=True, exist_ok=True)

        report_file = report_dir / "research_report.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"[REPORT] Saved report to {report_file}")
        return report

    def _generate_all_report(self) -> str:
        """Generate combined report for all treatments."""
        all_reports = {}

        for treatment_dir in self.results_dir.iterdir():
            if treatment_dir.is_dir():
                treatment = treatment_dir.name
                all_reports[treatment] = self._generate_single_report(treatment)

        # Generate batch summary
        lines = []
        lines.append("# Experiment Batch Report Summary")
        lines.append(f"\n**Experiment**: {self.experiment_name}")
        lines.append(f"**Generated**: {datetime.now().isoformat()}")
        lines.append("")
        lines.append("## Treatments Analyzed")
        lines.append("")

        for treatment, report in all_reports.items():
            lines.append(f"### {treatment}")
            # Extract key findings from report
            report_file = self.results_dir / treatment / "research_report.md"
            if report_file.exists():
                with open(report_file) as f:
                    content = f.read()
                    # Get first 200 chars as summary
                    summary = content[content.find("## Executive Summary"):].split("##")[2] if "## Executive Summary" in content else "See full report"
                    lines.append(f"```\n{summary[:200]}...\n```")
            lines.append("")

        summary_text = "\n".join(lines)

        summary_file = self.results_dir / "batch_report_summary.md"
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary_text)

        print(f"[REPORT] Saved batch summary to {summary_file}")
        return summary_text


def generate_report(experiment: str, treatment: Optional[str] = None) -> str:
    """Generate a report for the specified experiment."""
    generator = ReportGenerator(experiment, treatment)
    return generator.generate(treatment)


def batch_generate() -> Dict[str, str]:
    """Generate reports for all experiments."""
    results = {}
    for exp_name in EXPERIMENT_MODULES.keys():
        try:
            generator = ReportGenerator(exp_name)
            report = generator.generate()
            results[exp_name] = "SUCCESS"
        except Exception as e:
            results[exp_name] = f"ERROR: {str(e)}"
    return results


def main():
    parser = argparse.ArgumentParser(description="GAWorld Experiment Report Generator")
    parser.add_argument("action", choices=["generate", "batch"], help="Action to perform")
    parser.add_argument("--experiment", help="Experiment name (e.g., exp_polarization)")
    parser.add_argument("--treatment", help="Specific treatment to generate report for")

    args = parser.parse_args()

    if args.action == "generate":
        if not args.experiment:
            print("[ERROR] --experiment is required for generate action")
            return

        report = generate_report(args.experiment, args.treatment)
        print(report)

    elif args.action == "batch":
        print("[REPORT] Generating batch reports for all experiments...")
        results = batch_generate()
        print("\n=== Batch Report Generation Results ===")
        for exp, status in results.items():
            print(f"  {exp}: {status}")


if __name__ == "__main__":
    main()