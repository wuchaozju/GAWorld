# 实验提案：情绪传染与社交网络动力学

**提案编号**：EXP-EMO-001
**研究领域**：心理学 / 计算社会科学 / 网络科学
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

- 个体情绪如何受他人影响？
- "情绪传染"在社交网络中如何传播？
- 社交网络结构如何影响情绪传播速度和范围？

### 1.2 研究假设

- **H1**：情绪通过社交接触正向传染（快乐传染、悲伤也传染）
- **H2**：关系亲密度越高，情绪传染强度越大
- **H3**：社交网络中心性高的智能体更容易成为情绪传播的桥梁
- **H4**：情绪传染具有级联效应（一条微博可能影响整个朋友圈）

### 1.3 关键指标

| 指标 | 说明 | 测量方式 |
|------|------|---------|
| `emotion` | 情绪状态 (0-1) | 实时追踪 |
| `social_influence` | 易受他人影响程度 | CSV 初始 |
| `network_density` | 社交网络密度 | 实时追踪 |
| `relationship_strength` | 关系强度 | 社交互动历史 |
| `social_encounters` | 社交偶遇次数 | `SocialChainResolver` 输出 |

---

## 2. GAWorld 已有能力

| 能力 | 对应模块 | 说明 |
|------|---------|------|
| 六种情绪分类 | `dynamic_behavior.py` | 开心/压力/疲倦/无聊/焦虑/孤独 |
| 情绪驱动即兴行为 | `SpontaneityEngine` | 情绪触发行为池 |
| 社交偶遇链 | `SocialChainResolver` | 关系亲密度计算偶遇概率 |
| 社交网络追踪 | `network/` 输出 | `social_network.png` 社交图 |
| 行为传染机制 | `SocialChainResolver` |陌生人行为传染 |

---

## 3. 实验设计

### 3.1 实验类型

**社交网络追踪实验** + **情绪播种实验**（Emotional seeding experiment）

### 3.2 实验组设计

| 实验组 | 说明 | 设计目的 |
|--------|------|---------|
| Control | 无情绪播种，正常运行 | 基线 |
| Treatment-happy | Day 2 播种高情绪智能体 | 正向情绪传播 |
| Treatment-sad | Day 2 播种低情绪智能体 | 负向情绪传播 |
| Treatment-sparse | 降低网络密度后播种 | 网络密度影响 |

### 3.3 情绪播种方案

```python
# 播种设置
EMOTION_SEED = {
    "happy": {
        "seed_agents": [1, 5, 10],  # emotion=0.9
        "seed_value": 0.9,
        "inject_day": 2,
        "inject_hour": 8,
        "description": "播种开心情绪"
    },
    "sad": {
        "seed_agents": [3, 8, 15],  # emotion=0.2
        "seed_value": 0.2,
        "inject_day": 2,
        "inject_hour": 8,
        "description": "播种悲伤情绪"
    }
}
```

### 3.4 测量频率

- 每 4 小时（time step）记录所有智能体的情绪状态
- 记录每次社交偶遇事件（who met whom, when）
- 每日计算网络级别的情绪均值和方差

---

## 4. 实施代码

### 4.1 实验脚本：`experiments/emotion_contagion_exp.py`

```python
#!/usr/bin/env python3
"""
GAWorld 情绪传染实验

运行方式：
    python experiments/emotion_contagion_exp.py run --treatment treatment_happy --days 14 --seed 42

预期输出：
    output/experiments/emotion_contagion/<treatment>/emotion_timeseries.csv
    output/experiments/emotion_contagion/<treatment>/encounter_log.csv
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

EXPERIMENT_DIR = Path("output/experiments/emotion_contagion")

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
            "reduce_density_by": 0.5  # 降低50%网络密度
        },
        "description": "稀疏网络 + 开心情绪播种"
    }
}

def inject_emotion_seed(seed_config: dict):
    """通过修改智能体状态注入情绪种子"""
    # 这个函数应该在仿真前修改 CSV 状态
    # 或者通过 RAG 注入
    pass

def run_treatment(treatment: str, days: int, seed: int):
    """运行单个实验组"""
    config = TREATMENTS[treatment]
    exp_dir = EXPERIMENT_DIR / treatment
    exp_dir.mkdir(parents=True, exist_ok=True)

    # 准备情绪播种
    seed_config = config.get("emotion_seed")
    if seed_config:
        # 修改初始状态文件（创建临时副本）
        import shutil
        orig_csv = Path("data/hangzhou_agents_state_init.csv")
        temp_csv = exp_dir / "seed_state.csv"
        shutil.copy(orig_csv, temp_csv)

        # 修改种子智能体的情绪值
        df = pd.read_csv(orig_csv)
        for agent_id in seed_config["seed_agents"]:
            agent_idx = df[df["id"] == agent_id].index
            if len(agent_idx) > 0:
                df.loc[agent_idx, "emotion"] = seed_config["seed_value"]

        df.to_csv(temp_csv, index=False)

        # 设置环境变量指向临时文件
        os.environ["GAWORLD_AGENT_STATE_CSV"] = str(temp_csv)

    # 记录实验配置
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

    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}", file=sys.stderr)
        return False

    return True

def extract_emotion_timeseries(exp_dir: Path) -> pd.DataFrame:
    """从仿真结果中提取情绪时间序列"""
    state_file = exp_dir / "state" / "agent_state_history.csv"
    if not state_file.exists():
        return None

    df = pd.read_csv(state_file)
    return df[["day", "time", "agent_id", "emotion"]]

def compute_contagion_metrics(exp_dir: Path) -> dict:
    """计算情绪传染指标"""
    state_file = exp_dir / "state" / "agent_state_history.csv"
    if not state_file.exists():
        return {"error": "State file not found"}

    df = pd.read_csv(state_file)

    # 计算每日情绪均值和方差
    daily_stats = df.groupby("day").agg({
        "emotion": ["mean", "std", "min", "max"]
    }).reset_index()
    daily_stats.columns = ["day", "mean", "std", "min", "max"]

    # 计算情绪传染速度
    # 传染速度 = (Day N 平均情绪 - Day N-1 平均情绪) / Day N-1 平均情绪
    daily_stats["emotion_change"] = daily_stats["mean"].pct_change()

    # 计算网络级别的情绪同步性（使用标准差作为同步性反向指标）
    # std 越小表示情绪越同步
    daily_stats["sync_score"] = 1 - daily_stats["std"]  # 转换为正向指标

    # 找出情绪极值日期
    peak_happiness_day = daily_stats.loc[daily_stats["mean"].idxmax(), "day"]
    lowest_happiness_day = daily_stats.loc[daily_stats["mean"].idxmin(), "day"]

    # 计算种子智能体与其他智能体的情绪相关性
    treatment = exp_dir.name
    seed_agents = TREATMENTS.get(treatment, {}).get("emotion_seed", {}).get("seed_agents", [])

    if seed_agents:
        seed_emotion = df[df["agent_id"].isin(seed_agents)].groupby("day")["emotion"].mean()
        other_emotion = df[~df["agent_id"].isin(seed_agents)].groupby("day")["emotion"].mean()

        # 计算相关性
        correlation = seed_emotion.corr(other_emotion)
    else:
        correlation = None

    return {
        "daily_stats": daily_stats.to_dict(),
        "peak_happiness_day": int(peak_happiness_day) if pd.notna(peak_happiness_day) else None,
        "lowest_happiness_day": int(lowest_happiness_day) if pd.notna(lowest_happiness_day) else None,
        "seed_other_correlation": correlation,
        "final_mean_emotion": daily_stats.iloc[-1]["mean"] if len(daily_stats) > 0 else None,
        "final_sync_score": daily_stats.iloc[-1]["sync_score"] if len(daily_stats) > 0 else None
    }

def analyze_contagion_speed(exp_dir: Path) -> dict:
    """分析传染速度"""
    state_file = exp_dir / "state" / "agent_state_history.csv"
    if not state_file.exists():
        return {}

    df = pd.read_csv(state_file)
    treatment = exp_dir.name
    seed_agents = TREATMENTS.get(treatment, {}).get("emotion_seed", {}).get("seed_agents", [])

    if not seed_agents:
        return {}

    # 分别计算种子组和非种子组的时间序列
    seed_df = df[df["agent_id"].isin(seed_agents)]
    non_seed_df = df[~df["agent_id"].isin(seed_agents)]

    seed_daily = seed_df.groupby("day")["emotion"].mean()
    non_seed_daily = non_seed_df.groupby("day")["emotion"].mean()

    # 计算从种子到非种子的"传染延迟"
    # 找到非种子组情绪开始向种子方向变化的时间点
    results = {
        "seed_mean_trajectory": seed_daily.to_dict(),
        "non_seed_mean_trajectory": non_seed_daily.to_dict(),
        "initial_gap": seed_daily.iloc[0] - non_seed_daily.iloc[0] if len(seed_daily) > 0 and len(non_seed_daily) > 0 else None,
        "final_gap": seed_daily.iloc[-1] - non_seed_daily.iloc[-1] if len(seed_daily) > 0 and len(non_seed_daily) > 0 else None
    }

    return results

def compare_treatments():
    """对比所有实验组"""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = EXPERIMENT_DIR / treatment
        if exp_dir.exists():
            results[treatment] = {
                "contagion_metrics": compute_contagion_metrics(exp_dir),
                "contagion_speed": analyze_contagion_speed(exp_dir)
            }

    import json
    print(json.dumps(results, indent=2, ensure_ascii=False))

    with open(EXPERIMENT_DIR / "comparison_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return results

def plot_emotion_trajectories():
    """绘制情绪轨迹图"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not installed, skipping plot")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    for idx, treatment in enumerate(TREATMENTS.keys()):
        ax = axes[idx // 2, idx % 2]
        exp_dir = EXPERIMENT_DIR / treatment

        state_file = exp_dir / "state" / "agent_state_history.csv"
        if not state_file.exists():
            continue

        df = pd.read_csv(state_file)

        # 绘制每日平均情绪
        daily_mean = df.groupby("day")["emotion"].mean()
        daily_std = df.groupby("day")["emotion"].std()

        ax.plot(daily_mean.index, daily_mean.values, marker='o', label='Mean Emotion')
        ax.fill_between(daily_mean.index,
                        daily_mean.values - daily_std.values,
                        daily_mean.values + daily_std.values,
                        alpha=0.3, label='±1 Std')

        # 标记播种时间点
        seed_config = TREATMENTS[treatment].get("emotion_seed")
        if seed_config:
            inject_day = seed_config["inject_day"]
            ax.axvline(x=inject_day, color='red', linestyle='--', label='Seed Injection')
            ax.annotate(f"Seed: {seed_config['seed_value']}", xy=(inject_day, 0.9),
                       fontsize=8, color='red')

        ax.set_title(treatment)
        ax.set_xlabel("Day")
        ax.set_ylabel("Emotion (0-1)")
        ax.legend()
        ax.grid(True)

    plt.tight_layout()
    plt.savefig(EXPERIMENT_DIR / "emotion_trajectories.png", dpi=150)
    print(f"[EXP] Saved plot to {EXPERIMENT_DIR / 'emotion_trajectories.png'}")

def main():
    parser = argparse.ArgumentParser(description="情绪传染实验")
    parser.add_argument("action", choices=["run", "analyze", "compare", "plot"])
    parser.add_argument("--treatment", default="control",
                        help=f"实验组: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="仿真天数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()

    if args.action == "run":
        run_treatment(args.treatment, args.days, args.seed)
    elif args.action == "analyze":
        exp_dir = EXPERIMENT_DIR / args.treatment
        metrics = compute_contagion_metrics(exp_dir)
        import json
        print(json.dumps(metrics, indent=2))
    elif args.action == "compare":
        compare_treatments()
    elif args.action == "plot":
        plot_emotion_trajectories()

if __name__ == "__main__":
    import os
    main()
```

### 4.2 社交网络分析：`experiments/network_analysis.py`

```python
#!/usr/bin/env python3
"""
社交网络分析工具

分析网络结构对情绪传染的影响
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
import networkx as nx

class SocialNetworkAnalyzer:
    def __init__(self, exp_dir: Path):
        self.exp_dir = exp_dir
        self.encounter_log = []
        self.network = None

    def load_encounters(self) -> pd.DataFrame:
        """从日志中加载社交偶遇数据"""
        log_dir = self.exp_dir / "logs"
        encounters = []

        for log_file in log_dir.glob("agent_*.log"):
            agent_id = int(log_file.stem.split("_")[1])
            with open(log_file) as f:
                content = f.read()

            # 解析社交事件（需要根据实际日志格式调整）
            # 假设日志中包含 "[Encounter] Agent X met Agent Y at location Z"
            import re
            pattern = r"Agent (\d+) met Agent (\d+)"
            matches = re.findall(pattern, content)

            for m in matches:
                encounters.append({
                    "agent_1": int(m[0]),
                    "agent_2": int(m[1]),
                    "agent_source": agent_id
                })

        self.encounter_log = pd.DataFrame(encounters)
        return self.encounter_log

    def build_network(self) -> nx.Graph:
        """从偶遇日志构建社交网络"""
        G = nx.Graph()

        if len(self.encounter_log) == 0:
            return G

        # 统计每对智能体的偶遇次数作为边权重
        edge_counts = defaultdict(int)
        for _, row in self.encounter_log.iterrows():
            edge = tuple(sorted([row["agent_1"], row["agent_2"]]))
            edge_counts[edge] += 1

        for (a1, a2), count in edge_counts.items():
            G.add_edge(a1, a2, weight=count)

        self.network = G
        return G

    def compute_centrality(self) -> dict:
        """计算网络中心性指标"""
        if self.network is None:
            self.build_network()

        if len(self.network.nodes) == 0:
            return {}

        return {
            "degree_centrality": nx.degree_centrality(self.network),
            "betweenness_centrality": nx.betweenness_centrality(self.network),
            "closeness_centrality": nx.closeness_centrality(self.network)
        }

    def emotion_correlation_by_distance(self, emotion_df: pd.DataFrame) -> dict:
        """计算不同网络距离的智能体间的情绪相关性"""
        if self.network is None:
            self.build_network()

        # 获取所有智能体对的最短路径距离
        node_list = list(self.network.nodes())
        n = len(node_list)

        correlations_by_distance = defaultdict(list)

        for i in range(n):
            for j in range(i + 1, n):
                node_i = node_list[i]
                node_j = node_list[j]

                try:
                    distance = nx.shortest_path_length(self.network, node_i, node_j)
                except nx.NetworkXNoPath:
                    distance = float('inf')

                if distance == float('inf'):
                    continue

                # 获取两个智能体的情绪时间序列相关性
                emotion_i = emotion_df[emotion_df["agent_id"] == node_i]["emotion"].values
                emotion_j = emotion_df[emotion_df["agent_id"] == node_j]["emotion"].values

                if len(emotion_i) > 1 and len(emotion_j) > 1:
                    # 需要对齐时间，取较短的长度
                    min_len = min(len(emotion_i), len(emotion_j))
                    corr = np.corrcoef(emotion_i[:min_len], emotion_j[:min_len])[0, 1]

                    if not np.isnan(corr):
                        correlations_by_distance[distance].append(corr)

        # 计算每个距离的平均相关性
        result = {
            distance: np.mean(correlations)
            for distance, correlations in correlations_by_distance.items()
        }

        return result

    def identify_emotion_bridges(self, threshold: float = 0.7) -> list:
        """识别情绪传播桥梁节点（在网络中介位置且情绪传播影响力高）"""
        if self.network is None:
            self.build_network()

        centrality = self.compute_centrality()
        if not centrality:
            return []

        betweenness = centrality.get("betweenness_centrality", {})

        # 找出高介数中心性的节点
        sorted_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)

        bridges = []
        for node, score in sorted_betweenness[:10]:  # Top 10
            bridges.append({
                "agent_id": node,
                "betweenness": score,
                "likely_bridge": score > np.mean(list(betweenness.values()))
            })

        return bridges

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python network_analysis.py <exp_dir>")
        sys.exit(1)

    exp_dir = Path(sys.argv[1])
    analyzer = SocialNetworkAnalyzer(exp_dir)

    # 加载数据
    encounters = analyzer.load_encounters()
    print(f"Loaded {len(encounters)} encounter records")

    # 构建网络
    network = analyzer.build_network()
    print(f"Network: {network.number_of_nodes()} nodes, {network.number_of_edges()} edges")

    # 计算中心性
    centrality = analyzer.compute_centrality()
    print("\nTop 5 betweenness centrality nodes:")
    betweenness = centrality.get("betweenness_centrality", {})
    sorted_bc = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:5]
    for node, score in sorted_bc:
        print(f"  Agent {node}: {score:.4f}")

    # 保存结果
    results = {
        "centrality": centrality,
        "bridges": analyzer.identify_emotion_bridges()
    }

    with open(exp_dir / "network_analysis.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
```

---

## 5. 预期结果格式

### 5.1 情绪时间序列

```csv
day,time,agent_id,emotion,stress,econ_security
2,08:00,1,0.90,0.20,0.65  # 种子智能体
2,08:00,2,0.55,0.45,0.58  # 非种子
2,08:00,3,0.58,0.48,0.55
...
7,12:00,1,0.85,0.25,0.68  # 种子仍较高
7,12:00,2,0.72,0.35,0.62  # 开始接近
7,12:00,3,0.68,0.40,0.58  # 情绪上升
```

### 5.2 传染速度分析

```json
{
  "treatment_happy": {
    "seed_mean_trajectory": {"2": 0.90, "3": 0.88, "4": 0.85, ...},
    "non_seed_mean_trajectory": {"2": 0.55, "3": 0.57, "4": 0.62, ...},
    "initial_gap": 0.35,
    "final_gap": 0.15,
    "convergence_day": 7
  }
}
```

---

## 6. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 脚本开发 | 1天 |
| Phase 2 | 运行全部4组实验（各14天） | 2天 |
| Phase 3 | 数据分析与可视化 | 1天 |
| Phase 4 | 网络分析与报告 | 1天 |
| **总计** | | **5天** |

---

## 7. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| 情绪传染 | Hatfield et al. (1993) *Emotional Contagion* | 量化传染速度和网络距离效应 |
| 社会网络与幸福感 | Fowler & Christakis (2008) *Dynamic spread of happiness* | 验证纵向传播路径 |
| 情绪级联 | Kramer et al. (2014) *Experimental evidence of massive-scale emotional contagion* | 提供可控的A/B实验设计 |

---

## 8. 扩展方向

### 8.1 长期情绪持续性

观察初始情绪波动是否在整个仿真期间持续影响智能体

### 8.2 情绪反转实验

播种负面情绪后，在Day 7注入正向干预，观察情绪恢复路径

### 8.3 网络结构干预

测试"增加弱连接"是否比"强化强连接"更有效提升整体情绪