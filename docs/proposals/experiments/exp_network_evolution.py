#!/usr/bin/env python3
"""
GAWorld Experiment: Network Evolution (EXP-NET-001)

Studies social network evolution and community structure formation.

Usage:
    python exp_network_evolution.py run --treatment natural_evolution --days 30 --seed 42
    python exp_network_evolution.py track --treatment natural_evolution --days 30
    python exp_network_evolution.py compare
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent))
from run_experiment import ExperimentRunner, RESULTS_DIR


TREATMENTS = {
    "natural_evolution": {
        "homophily_weight": 1.0,
        "event_disruption": False,
        "bridge_creation": False,
        "description": "自然演化30天"
    },
    "homophily_boost": {
        "homophily_weight": 1.3,
        "event_disruption": False,
        "bridge_creation": False,
        "description": "增强同质性连接"
    },
    "event_disruption": {
        "homophily_weight": 1.0,
        "event_disruption": True,
        "bridge_creation": False,
        "description": "外部事件扰动"
    },
    "bridge_creation": {
        "homophily_weight": 1.0,
        "event_disruption": False,
        "bridge_creation": True,
        "description": "增加桥梁节点"
    }
}


class ExpNetworkEvolution(ExperimentRunner):
    """Network evolution experiment runner."""

    def __init__(self, treatment: str = "natural_evolution", days: int = 30, seed: int = 42):
        exp_name = "exp_network_evolution"
        exp_dir = RESULTS_DIR / exp_name / treatment

        super().__init__(exp_name, exp_dir, default_days=days, default_seed=seed)
        self.treatment = treatment
        self.config = TREATMENTS.get(treatment, TREATMENTS["natural_evolution"])

    def run(self) -> bool:
        """Run the network evolution experiment."""
        config_record = {
            "treatment": self.treatment,
            "config": self.config,
            "days": self.default_days,
            "seed": self.default_seed,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.experiment_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(config_record, f, indent=2, ensure_ascii=False)

        env_vars = {
            "GAWORLD_HOMOPHILY_WEIGHT": str(self.config["homophily_weight"])
        }

        if self.config.get("event_disruption"):
            env_vars["GAWORLD_DISRUPTION_DAY"] = "7"
            env_vars["GAWORLD_DISRUPTION_TYPE"] = "policy_event"

        return self.run_simulation(
            days=self.default_days,
            seed=self.default_seed,
            env_vars=env_vars
        )

    def build_network(self, day: Optional[int] = None) -> "nx.Graph":
        """Build social network from logs."""
        if not NETWORKX_AVAILABLE:
            print("[WARN] networkx not available, returning empty graph")
            return None

        G = nx.Graph()
        log_dir = self.experiment_dir / "logs"

        if not log_dir.exists():
            return G

        encounters = defaultdict(int)

        for log_file in log_dir.glob("agent_*.log"):
            with open(log_file) as f:
                content = f.read()

            pattern = r"Agent (\d+) met Agent (\d+)"
            for match in re.finditer(pattern, content):
                node1, node2 = int(match.group(1)), int(match.group(2))
                edge = tuple(sorted([node1, node2]))
                encounters[edge] += 1

        for (n1, n2), weight in encounters.items():
            G.add_edge(n1, n2, weight=weight)

        return G

    def compute_network_metrics(self, G: "nx.Graph") -> Dict[str, Any]:
        """Compute network metrics."""
        if G is None or G.number_of_nodes() == 0:
            return {}

        metrics = {
            "n_nodes": G.number_of_nodes(),
            "n_edges": G.number_of_edges(),
            "density": nx.density(G),
            "avg_degree": sum(dict(G.degree()).values()) / G.number_of_nodes(),
            "clustering_coefficient": nx.average_clustering(G),
            "num_components": nx.number_connected_components(G)
        }

        if G.number_of_nodes() > 1:
            degree_cent = nx.degree_centrality(G)
            between_cent = nx.betweenness_centrality(G)
            close_cent = nx.closeness_centrality(G)

            metrics["avg_degree_centrality"] = float(np.mean(list(degree_cent.values())))
            metrics["avg_betweenness_centrality"] = float(np.mean(list(between_cent.values())))
            metrics["avg_closeness_centrality"] = float(np.mean(list(close_cent.values())))

            # Top betweenness nodes
            sorted_between = sorted(between_cent.items(), key=lambda x: x[1], reverse=True)[:5]
            metrics["top_betweenness_nodes"] = [{"agent_id": n, "score": float(s)} for n, s in sorted_between]

        # Homophily (simplified)
        same_group_edges = 0
        total_edges = G.number_of_edges()
        for n1, n2 in G.edges():
            if (n1 % 3) == (n2 % 3):
                same_group_edges += 1
        metrics["homophily"] = same_group_edges / total_edges if total_edges > 0 else 0.0

        # Modularity
        try:
            from networkx.algorithms.community import louvain_communities
            communities = louvain_communities(G)
            metrics["num_communities"] = len(communities)
            metrics["modularity"] = nx.algorithms.community.modularity(G, communities)
        except Exception as e:
            metrics["community_error"] = str(e)

        return metrics

    def track_evolution(self, days: int) -> pd.DataFrame:
        """Track network metrics over days."""
        results = []

        for day in range(1, days + 1):
            print(f"[EXP] Computing metrics for day {day}...")
            G = self.build_network(day=day)
            metrics = self.compute_network_metrics(G)
            metrics["day"] = day
            results.append(metrics)

        df = pd.DataFrame(results)
        df.to_csv(self.experiment_dir / "network_metrics.csv", index=False)
        return df

    def analyze(self) -> Dict[str, Any]:
        """Analyze network evolution results."""
        metrics_file = self.experiment_dir / "network_metrics.csv"

        if not metrics_file.exists():
            # Try to build metrics from logs
            G = self.build_network()
            if G is None:
                return {"error": "No network data available"}

            metrics = self.compute_network_metrics(G)
            return {
                "treatment": self.treatment,
                "final_metrics": metrics
            }

        df = pd.read_csv(metrics_file)

        results = {
            "treatment": self.treatment,
            "final_metrics": df.iloc[-1].to_dict() if len(df) > 0 else {},
            "density_trend": df["density"].tolist() if "density" in df.columns else [],
            "homophily_trend": df["homophily"].tolist() if "homophily" in df.columns else []
        }

        if "modularity" in df.columns:
            results["modularity_trend"] = df["modularity"].tolist()

        return results


def run_treatment(treatment: str, days: int, seed: int) -> bool:
    """Run a single treatment."""
    exp = ExpNetworkEvolution(treatment=treatment, days=days, seed=seed)
    return exp.run()


def track_treatment(treatment: str, days: int) -> pd.DataFrame:
    """Track evolution of a treatment."""
    exp = ExpNetworkEvolution(treatment=treatment, days=days)
    return exp.track_evolution(days)


def compare_treatments() -> Dict[str, Any]:
    """Compare all treatments."""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = RESULTS_DIR / "exp_network_evolution" / treatment
        if exp_dir.exists():
            exp = ExpNetworkEvolution(treatment=treatment)
            results[treatment] = exp.analyze()

    print("\n=== Network Evolution Experiment Comparison ===\n")
    print(f"{'Treatment':<20} {'Final Density':<14} {'Modularity':<12} {'Communities':<12}")
    print("-" * 60)
    for treatment, res in results.items():
        if "error" not in res:
            fm = res.get("final_metrics", {})
            dens = fm.get("density", 0) or 0
            mod = fm.get("modularity", 0) or 0
            comm = fm.get("num_communities", 0) or 0
            print(f"{treatment:<20} {dens:<14.4f} {mod:<12.4f} {comm:<12}")

    comparison_file = RESULTS_DIR / "exp_network_evolution" / "comparison_results.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    return results


def main():
    parser = argparse.ArgumentParser(description="Network Evolution Experiment (EXP-NET-001)")
    parser.add_argument("action", choices=["run", "track", "compare"], help="Action to perform")
    parser.add_argument("--treatment", default="natural_evolution", help=f"Treatment: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=30, help="Simulation days")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    if args.action == "run":
        success = run_treatment(args.treatment, args.days, args.seed)
        sys.exit(0 if success else 1)
    elif args.action == "track":
        df = track_treatment(args.treatment, args.days)
        print(f"Tracked {len(df)} days")
        print(df.head())
    elif args.action == "compare":
        results = compare_treatments()
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()