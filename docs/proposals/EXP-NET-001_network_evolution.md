# 实验提案：社交网络演化与社区结构形成

**提案编号**：EXP-NET-001
**研究领域**：网络科学 / 计算社会科学
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

- 社交网络如何从随机连接演化为社区结构？
- 什么因素驱动同质性（homophily）和社区形成？
- 信息和行为在网络中如何传播？哪些节点最关键？

### 1.2 研究假设

- **H1**：相似特征的智能体之间更容易形成连接（同质性效应）
- **H2**：高网络中心性的智能体在信息传播中起关键作用
- **H3**：社区结构随着仿真天数增加而加强
- **H4**：外部事件（如政策变化）会暂时打破现有社区结构

### 1.3 关键指标

| 指标 | 说明 | 测量方式 |
|------|------|---------|
| `network_density` | 网络密度（边数/最大边数） | networkx 计算 |
| `homophily` | 同质性水平 | 相似智能体间连接比例 |
| `modularity` | 社区模块度 | Louvain 算法 |
| `betweenness_centrality` | 介数中心性 | networkx 计算 |
| `clustering_coefficient` | 聚类系数 | networkx 计算 |

---

## 2. GAWorld 社交网络能力

| 能力 | 说明 |
|------|------|
| 社交偶遇链 | `SocialChainResolver` 在同地点产生连接 |
| 关系记忆 | 追踪关系强度变化 |
| 行为传染 | 陌生人行为传染（跟着排队等） |
| 网络可视化 | `output/network/social_network.png` |

---

## 3. 实验设计

### 3.1 实验类型

**纵向网络追踪**（Longitudinal network tracking）+ **网络扰动实验**（Network perturbation）

### 3.2 实验组设计

| 实验组 | 说明 | 关键变量 |
|--------|------|---------|
| Natural-evolution | 自然演化14天 | 无干预 |
| Homophily-boost | 增强相似智能体间连接倾向 | 同质性连接权重+0.3 |
| Event-disruption | 注入外部事件观察网络响应 | Day 7 注入政策事件 |
| Bridge-creation | 增加跨社区连接 | 人为创建桥梁节点 |

---

## 4. 实施代码

### 4.1 实验脚本：`experiments/network_evolution_exp.py`

```python
#!/usr/bin/env python3
"""
GAWorld 社交网络演化实验

运行方式：
    python experiments/network_evolution_exp.py run --treatment natural_evolution --days 30 --seed 42

预期输出：
    output/experiments/network_evolution/<treatment>/network_snapshots/
    output/experiments/network_evolution/<treatment>/network_metrics.csv
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import networkx as nx
from collections import defaultdict

EXPERIMENT_DIR = Path("output/experiments/network_evolution")

TREATMENTS = {
    "natural_evolution": {
        "homophily_weight": 1.0,
        "event_disruption": False,
        "bridge_creation": False,
        "description": "自然演化30天"
    },
    "homophily_boost": {
        "homophily_weight": 1.3,  # 增加同质性倾向
        "event_disruption": False,
        "bridge_creation": False,
        "description": "增强同质性连接"
    },
    "event_disruption": {
        "homophily_weight": 1.0,
        "event_disruption": True,  # Day 7 注入外部事件
        "bridge_creation": False,
        "description": "外部事件扰动"
    },
    "bridge_creation": {
        "homophily_weight": 1.0,
        "event_disruption": False,
        "bridge_creation": True,  # 人为创建跨社区连接
        "description": "增加桥梁节点"
    }
}

def run_network_simulation(treatment: str, days: int, seed: int) -> bool:
    """运行网络演化仿真"""
    config = TREATMENTS[treatment]
    exp_dir = EXPERIMENT_DIR / treatment
    exp_dir.mkdir(parents=True, exist_ok=True)

    # 设置环境变量
    import os
    os.environ["GAWORLD_HOMOPHILY_WEIGHT"] = str(config["homophily_weight"])

    if config.get("event_disruption"):
        # 标记事件注入时间
        os.environ["GAWORLD_DISRUPTION_DAY"] = "7"
        os.environ["GAWORLD_DISRUPTION_TYPE"] = "policy_event"

    # 记录配置
    config_record = {
        "treatment": treatment,
        "config": config,
        "days": days,
        "seed": seed,
        "timestamp": datetime.now().isoformat()
    }
    with open(exp_dir / "experiment_config.json", "w") as f:
        json.dump(config_record, f, indent=2, ensure_ascii=False)

    # 运行仿真
    cmd = [
        "python", "generative_city_sim.py", "run",
        "--sim-days", str(days),
        "--seed", str(seed),
        "--output-dir", str(exp_dir)
    ]

    print(f"[EXP] Running treatment={treatment} days={days} seed={seed}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    return result.returncode == 0

def build_network_from_logs(exp_dir: Path, day: int = None) -> nx.Graph:
    """从日志构建社交网络"""
    G = nx.Graph()
    log_dir = exp_dir / "logs"

    if not log_dir.exists():
        return G

    # 收集所有偶遇事件
    encounters = defaultdict(int)

    for log_file in log_dir.glob("agent_*.log"):
        agent_id = int(log_file.stem.split("_")[1])

        with open(log_file) as f:
            content = f.read()

        # 解析偶遇事件（格式：[Encounter] Agent X met Agent Y at Location Z）
        import re
        pattern = r"Agent (\d+) met Agent (\d+)"

        for match in re.finditer(pattern, content):
            node1, node2 = int(match.group(1)), int(match.group(2))
            edge = tuple(sorted([node1, node2]))
            encounters[edge] += 1

    # 添加边到图
    for (n1, n2), weight in encounters.items():
        G.add_edge(n1, n2, weight=weight)

    return G

def compute_network_metrics(G: nx.Graph) -> dict:
    """计算网络指标"""
    if G.number_of_nodes() == 0:
        return {}

    metrics = {
        "n_nodes": G.number_of_nodes(),
        "n_edges": G.number_of_edges(),
        "density": nx.density(G),
        "avg_degree": sum(dict(G.degree()).values()) / G.number_of_nodes(),
        "clustering_coefficient": nx.average_clustering(G),
        "num_components": nx.number_connected_components(G),
        "largest_component_size": len(max(nx.connected_components(G), key=len)) if nx.number_connected_components(G) > 0 else 0
    }

    # 计算中心性指标
    if G.number_of_nodes() > 1:
        degree_cent = nx.degree_centrality(G)
        between_cent = nx.betweenness_centrality(G)
        close_cent = nx.closeness_centrality(G)

        metrics["avg_degree_centrality"] = np.mean(list(degree_cent.values()))
        metrics["avg_betweenness_centrality"] = np.mean(list(between_cent.values()))
        metrics["avg_closeness_centrality"] = np.mean(list(close_cent.values()))
        metrics["top_betweenness_nodes"] = sorted(between_cent.items(), key=lambda x: x[1], reverse=True)[:5]

    # 计算同质性
    homophily = compute_homophily(G)
    metrics["homophily"] = homophily

    # 计算模块度（使用 Louvain）
    try:
        from networkx.algorithms.community import louvain_communities
        communities = louvain_communities(G)
        metrics["num_communities"] = len(communities)
        metrics["modularity"] = nx.algorithms.community.modularity(G, communities)

        # 保存社区分配
        community_assignment = {}
        for i, comm in enumerate(communities):
            for node in comm:
                community_assignment[node] = i
        metrics["community_assignment"] = community_assignment
    except Exception as e:
        metrics["community_error"] = str(e)

    return metrics

def compute_homophily(G: nx.Graph) -> float:
    """
    计算同质性：相似智能体间连接的比例

    需要加载智能体特征来定义"相似"
    这里简化为基于 ID 的某种划分（如 ID%3）
    """
    if G.number_of_edges() == 0:
        return 0.0

    # 简化：定义"相似"为同一组（ID % 3）
    same_group_edges = 0
    total_edges = G.number_of_edges()

    for n1, n2 in G.edges():
        if (n1 % 3) == (n2 % 3):  # 简化：按 ID 模 3 分组
            same_group_edges += 1

    return same_group_edges / total_edges if total_edges > 0 else 0.0

def snapshot_network(exp_dir: Path, day: int):
    """保存网络快照"""
    snapshot_dir = exp_dir / "network_snapshots" / f"day_{day}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    G = build_network_from_logs(exp_dir, day)

    # 保存边列表
    nx.write_edgelist(G, snapshot_dir / "edges.txt")

    # 保存指标
    metrics = compute_network_metrics(G)
    with open(snapshot_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics

def track_network_evolution(exp_dir: Path, days: int):
    """追踪网络演化"""
    results = []

    for day in range(1, days + 1):
        print(f"[EXP] Snapshotting day {day}...")
        metrics = snapshot_network(exp_dir, day)
        metrics["day"] = day
        results.append(metrics)

    # 保存时间序列
    df = pd.DataFrame(results)
    df.to_csv(exp_dir / "network_metrics.csv", index=False)

    return df

def compare_treatments():
    """对比所有实验组的网络演化"""
    results = {}

    for treatment in TREATMENTS.keys():
        exp_dir = EXPERIMENT_DIR / treatment
        if exp_dir.exists():
            metrics_file = exp_dir / "network_metrics.csv"
            if metrics_file.exists():
                df = pd.read_csv(metrics_file)
                results[treatment] = {
                    "final_density": df["density"].iloc[-1] if len(df) > 0 else None,
                    "final_modularity": df["modularity"].iloc[-1] if "modularity" in df.columns else None,
                    "final_num_communities": df["num_communities"].iloc[-1] if "num_communities" in df.columns else None,
                    "evolution_trend": df[["day", "density", "homophily"]].to_dict()
                }

    import json
    print(json.dumps(results, indent=2, ensure_ascii=False))

    with open(EXPERIMENT_DIR / "comparison_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return results

def plot_network_evolution():
    """绘制网络演化图"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not installed, skipping plot")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    for idx, treatment in enumerate(TREATMENTS.keys()):
        ax = axes[idx // 2, idx % 2]
        exp_dir = EXPERIMENT_DIR / treatment

        metrics_file = exp_dir / "network_metrics.csv"
        if not metrics_file.exists():
            continue

        df = pd.read_csv(metrics_file)

        # 绘制密度和模块度演化
        ax.plot(df["day"], df["density"], label="Density", marker='o')
        if "modularity" in df.columns:
            ax.plot(df["day"], df["modularity"], label="Modularity", marker='x')

        ax.set_title(treatment)
        ax.set_xlabel("Day")
        ax.set_ylabel("Metric Value")
        ax.legend()
        ax.grid(True)

    plt.tight_layout()
    plt.savefig(EXPERIMENT_DIR / "network_evolution.png", dpi=150)
    print(f"[EXP] Saved plot to {EXPERIMENT_DIR / 'network_evolution.png'}")

def main():
    parser = argparse.ArgumentParser(description="社交网络演化实验")
    parser.add_argument("action", choices=["run", "track", "compare", "plot"])
    parser.add_argument("--treatment", default="natural_evolution",
                        help=f"实验组: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=30, help="仿真天数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()

    if args.action == "run":
        run_network_simulation(args.treatment, args.days, args.seed)
    elif args.action == "track":
        exp_dir = EXPERIMENT_DIR / args.treatment
        track_network_evolution(exp_dir, args.days)
    elif args.action == "compare":
        compare_treatments()
    elif args.action == "plot":
        plot_network_evolution()

if __name__ == "__main__":
    main()
```

### 4.2 网络中心性分析：`experiments/network_centrality.py`

```python
#!/usr/bin/env python3
"""
网络中心性分析工具

识别关键节点和信息传播桥梁
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
import networkx as nx

class NetworkCentralityAnalyzer:
    def __init__(self, exp_dir: Path):
        self.exp_dir = exp_dir
        self.G = None

    def load_network(self) -> nx.Graph:
        """加载网络"""
        from experiments.network_evolution_exp import build_network_from_logs
        self.G = build_network_from_logs(self.exp_dir)
        return self.G

    def compute_all_centralities(self) -> dict:
        """计算所有中心性指标"""
        if self.G is None:
            self.load_network()

        if self.G.number_of_nodes() == 0:
            return {}

        degree_cent = nx.degree_centrality(self.G)
        between_cent = nx.betweenness_centrality(self.G)
        close_cent = nx.closeness_centrality(self.G)
        pagerank = nx.pagerank(self.G)

        return {
            "degree_centrality": degree_cent,
            "betweenness_centrality": between_cent,
            "closeness_centrality": close_cent,
            "pagerank": pagerank
        }

    def identify_key_nodes(self, top_n: int = 10) -> dict:
        """识别关键节点"""
        centralities = self.compute_all_centralities()

        key_nodes = {}

        for metric_name, cent_dict in centralities.items():
            sorted_cent = sorted(cent_dict.items(), key=lambda x: x[1], reverse=True)
            key_nodes[f"top_{metric_name}"] = [
                {"agent_id": int(node), "score": float(score)}
                for node, score in sorted_cent[:top_n]
            ]

        # 综合排名
        all_scores = defaultdict(lambda: {"score": 0, "count": 0})
        for metric_name, cent_dict in centralities.items():
            for node, score in cent_dict.items():
                all_scores[int(node)]["score"] += score
                all_scores[int(node)]["count"] += 1

        # 平均得分
        for node in all_scores:
            all_scores[node]["avg_score"] = all_scores[node]["score"] / all_scores[node]["count"]

        overall_ranking = sorted(all_scores.items(), key=lambda x: x[1]["avg_score"], reverse=True)

        key_nodes["overall_top"] = [
            {"agent_id": node, "avg_centrality": data["avg_score"]}
            for node, data in overall_ranking[:top_n]
        ]

        return key_nodes

    def find_bridges(self) -> list:
        """找出信息传播桥梁节点"""
        if self.G is None:
            self.load_network()

        # 桥梁识别：介数中心性高且连接不同社区
        between_cent = nx.betweenness_centrality(self.G)

        # 找出介数中心性显著高于平均的节点
        avg_between = np.mean(list(between_cent.values()))
        std_between = np.std(list(between_cent.values()))

        bridges = []
        for node, score in between_cent.items():
            if score > avg_between + 2 * std_between:
                bridges.append({
                    "agent_id": int(node),
                    "betweenness": float(score),
                    "is_bridge": True
                })

        bridges.sort(key=lambda x: x["betweenness"], reverse=True)

        return bridges[:10]

    def compute_influence_spread(self, seed_nodes: list) -> dict:
        """
        计算从种子节点开始的影响力传播

        使用简单的 BFS 模拟传播
        """
        if self.G is None:
            self.load_network()

        if not seed_nodes:
            return {}

        # 简单传播模型：每步传播到所有邻居
        visited = set(seed_nodes)
        frontier = set(seed_nodes)
        step = 0
        spread_stats = {0: len(seed_nodes)}

        while frontier and step < 10:
            step += 1
            new_frontier = set()

            for node in frontier:
                neighbors = set(self.G.neighbors(node))
                new_frontier.update(neighbors - visited)

            visited.update(new_frontier)
            frontier = new_frontier
            spread_stats[step] = len(visited)

        return {
            "seed_nodes": seed_nodes,
            "spread_by_step": spread_stats,
            "total_reached": len(visited),
            "spread_rate": len(visited) / (step + 1)
        }

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python network_centrality.py <exp_dir>")
        sys.exit(1)

    exp_dir = Path(sys.argv[1])
    analyzer = NetworkCentralityAnalyzer(exp_dir)

    # 分析中心性
    print("=== Key Nodes ===")
    key_nodes = analyzer.identify_key_nodes()
    import json
    print(json.dumps(key_nodes["overall_top"], indent=2))

    # 找桥梁
    print("\n=== Bridge Nodes ===")
    bridges = analyzer.find_bridges()
    print(json.dumps(bridges, indent=2))

    # 影响力传播模拟
    print("\n=== Influence Spread from Top 5 ===")
    top5 = [n["agent_id"] for n in key_nodes["overall_top"][:5]]
    spread = analyzer.compute_influence_spread(top5)
    print(json.dumps(spread, indent=2))

if __name__ == "__main__":
    main()
```

---

## 5. 预期结果格式

### 5.1 网络指标时间序列

```csv
day,n_nodes,n_edges,density,avg_degree,clustering_coefficient,modularity,homophily
1,50,120,0.098,4.8,0.15,0.32,0.45
7,50,185,0.151,7.4,0.22,0.41,0.52
14,50,220,0.180,8.8,0.28,0.48,0.58
30,50,280,0.229,11.2,0.35,0.55,0.65
```

### 5.2 关键节点排名

```json
{
  "overall_top": [
    {"agent_id": 23, "avg_centrality": 0.182},
    {"agent_id": 8, "avg_centrality": 0.165},
    {"agent_id": 45, "avg_centrality": 0.148}
  ],
  "top_betweenness_centrality": [
    {"agent_id": 23, "score": 0.285},
    {"agent_id": 31, "score": 0.198}
  ]
}
```

---

## 6. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 脚本开发 | 1天 |
| Phase 2 | 运行全部4组实验（各30天） | 4天 |
| Phase 3 | 网络快照追踪 | 1天 |
| Phase 4 | 可视化与报告 | 2天 |
| **总计** | | **8天** |

---

## 7. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| 同质性 | McPherson et al. (2001) *Birds of a Feather* | 量化同质性对网络形成的影响 |
| 社区检测 | Blondel et al. (2008) *Louvain Algorithm* | 应用 Louvain 检测社区结构 |
| 影响力最大化 | Kempe et al. (2003) *Influence Maximization* | 识别关键传播节点 |

---

## 8. 扩展方向

### 8.1 信息级联研究

结合 EXP-INFO-001，观察信息如何在网络中传播

### 8.2 动态网络分析

研究边的增减动态（谁在失去连接，谁在获得新连接）

### 8.3 多层网络

同时分析社交网络和社交媒体转发网络的交互