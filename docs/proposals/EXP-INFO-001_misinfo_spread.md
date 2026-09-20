# 实验提案：信息传播与误信息扩散研究

**提案编号**：EXP-INFO-001
**研究领域**：社会科学 / 计算社会科学
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

社交网络中的误信息如何传播？不同认知水平、风险偏好的智能体对误信息的接受度差异如何？

### 1.2 研究假设

- **H1**：社交网络密度越高，误信息传播速度越快
- **H2**：风险偏好高的智能体更容易传播未验证信息
- **H3**：平台依赖度高的智能体更易接受平台推送的误信息
- **H4**：跨观点曝光（diversity exposure）能降低误信息接受率

### 1.3 预期产出

- 传播动力学模型参数（传播率、潜伏期、恢复率）
- 不同智能体特征的传播敏感性排名
- 误信息防御策略效果评估

---

## 2. GAWorld 已有能力

| 能力 | 对应模块 | 说明 |
|------|---------|------|
| `misinformation_risk` 指标 | `intervention_policy.py` | 每 step 记录误信息风险得分 |
| 社交偶遇链 | `SocialChainResolver` | 行为传染机制 |
| RAG 注入 | CLI `rag-add` | 注入信息种子 |
| 关系网络追踪 | `network_density`, `homophily` | 网络结构变量 |
| 智能体特征 | CSV 种子数据 | `risk_preference`, `platform_dependence` |

---

## 3. 实验设计

### 3.1 实验类型

**对照实验**（Cross-condition comparison）+ **时间序列追踪**（Longitudinal tracking）

### 3.2 实验组设计

| 实验组 | 说明 | 样本量 |
|--------|------|--------|
| Control | 无信息注入，正常运行 | 50 |
| Treatment-A | 注入单条误信息，观察传播 | 50 |
| Treatment-B | 注入误信息 + 高跨观点曝光干预 | 50 |
| Treatment-C | 网络结构改变（低密度） | 50 |

注：可通过修改 seed 复用同一批智能体运行多个组

### 3.3 信息注入方案

```python
# 通过 RAG 注入的信息内容
MISINFO_SEED = {
    "text": "听说地铁下个月要涨价到10元了，大家赶紧去充值交通卡",
    "timestamp": "Day1 08:00",
    "source": "experiment_misinfo",
    "target_agent_id": 1  # 从智能体1开始注入
}
```

### 3.4 测量指标

| 指标 | 测量方式 | 测量频率 |
|------|---------|---------|
| `misinformation_risk` | 干预模块输出 | 每 step |
| 信息接受率 | 智能体对话/反思中出现关键词 | 每日 |
| 传播路径 | 记录哪些智能体知道了这条信息 | 实时 |
| 行为变化 | 出行决策、社交模式变化 | 每日 |
| 传播延迟 | 从注入到扩散到50%智能体的时间 | 每日统计 |

---

## 4. 实施代码

### 4.1 实验脚本：`experiments/misinfo_spread.py`

```python
#!/usr/bin/env python3
"""
GAWorld 误信息传播实验

运行方式：
    python experiments/misinfo_spread.py run --treatment A --days 7 --seed 42

预期输出：
    output/experiments/misinfo_spread/<treatment>/misinfo_metrics.csv
"""

import argparse
import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from intervention_policy import evaluate_intervention

# 实验配置
EXPERIMENT_CONFIG = {
    "control": {
        "misinfo_seed": None,
        "intervention_enabled": True,
        "description": "无信息注入基线"
    },
    "treatment_a": {
        "misinfo_seed": {
            "text": "听说地铁下个月要涨价到10元了，大家赶紧去充值交通卡",
            "target_agent_id": 1,
            "day": 1,
            "hour": 8
        },
        "intervention_enabled": True,
        "description": "单条误信息注入"
    },
    "treatment_b": {
        "misinfo_seed": {
            "text": "听说地铁下个月要涨价到10元了，大家赶紧去充值交通卡",
            "target_agent_id": 1,
            "day": 1,
            "hour": 8
        },
        "intervention_enabled": True,
        "high_diversity_mode": True,  # 增强跨观点曝光
        "description": "误信息 + 强干预"
    }
}

def run_experiment(treatment: str, days: int, seed: int):
    """运行单个实验组"""
    config = EXPERIMENT_CONFIG[treatment]
    exp_dir = Path(f"output/experiments/misinfo_spread/{treatment}")
    exp_dir.mkdir(parents=True, exist_ok=True)

    # 构建实验命令
    cmd = [
        "python", "generative_city_sim.py", "run",
        "--sim-days", str(days),
        "--seed", str(seed),
        "--output-dir", str(exp_dir)
    ]

    # 注入误信息（通过环境变量或配置文件）
    if config["misinfo_seed"]:
        seed_info = config["misinfo_seed"]
        os.environ["GAWORLD_MISINFO_SEED"] = json.dumps(seed_info)

    # 记录实验配置
    with open(exp_dir / "experiment_config.json", "w") as f:
        json.dump({
            "treatment": treatment,
            "config": config,
            "days": days,
            "seed": seed,
            "timestamp": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)

    # 运行仿真
    print(f"[EXP] Running treatment={treatment} days={days} seed={seed}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return False

    return True

def analyze_results(treatment: str):
    """分析实验结果"""
    exp_dir = Path(f"output/experiments/misinfo_spread/{treatment}")
    metrics_file = exp_dir / "intervention" / "intervention_metrics.csv"

    if not metrics_file.exists():
        print(f"[WARN] Metrics file not found: {metrics_file}")
        return None

    # 读取并分析数据
    import pandas as pd
    df = pd.read_csv(metrics_file)

    results = {
        "treatment": treatment,
        "total_agents": df["agent_id"].nunique(),
        "days": df["day"].nunique(),
        "avg_misinfo_risk": df.groupby("day")["misinformation_risk"].mean().to_dict(),
        "peak_misinfo_risk": df["misinformation_risk"].max(),
        "final_misinfo_risk": df[df["day"] == df["day"].max()]["misinformation_risk"].mean()
    }

    return results

def main():
    parser = argparse.ArgumentParser(description="误信息传播实验")
    parser.add_argument("action", choices=["run", "analyze", "compare"])
    parser.add_argument("--treatment", default="treatment_a",
                        help="实验组: control, treatment_a, treatment_b")
    parser.add_argument("--days", type=int, default=7, help="仿真天数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--compare-all", action="store_true", help="对比所有实验组")

    args = parser.parse_args()

    if args.action == "run":
        run_experiment(args.treatment, args.days, args.seed)
    elif args.action == "analyze":
        results = analyze_results(args.treatment)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif args.action == "compare":
        all_results = {}
        for treatment in ["control", "treatment_a", "treatment_b"]:
            results = analyze_results(treatment)
            if results:
                all_results[treatment] = results

        print(json.dumps(all_results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

### 4.2 信息追踪模块：`experiments/misinfo_tracker.py`

```python
#!/usr/bin/env python3
"""
误信息传播追踪器

追踪每条信息从注入到传播的全过程
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

class MisinfoTracker:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.misinfo_events = []
        self.propagation_graph = defaultdict(list)  # agent_id -> [(time, source_id)]

    def inject_seed(self, agent_id: int, text: str, day: int, hour: int):
        """注入信息种子"""
        self.misinfo_events.append({
            "type": "seed",
            "agent_id": agent_id,
            "text": text,
            "day": day,
            "hour": hour,
            "timestamp": datetime.now().isoformat()
        })
        self.propagation_graph[agent_id].append((f"Day{day}H{hour}", "SEED"))

    def record_spread(self, from_agent: int, to_agent: int, time: str, context: str):
        """记录一次信息传播"""
        self.propagation_graph[to_agent].append((time, from_agent))

    def load_from_logs(self):
        """从运行日志中提取信息传播事件"""
        log_dir = self.output_dir / "logs"
        if not log_dir.exists():
            return

        for log_file in log_dir.glob("agent_*.log"):
            agent_id = int(re.search(r"agent_(\d+)", log_file.stem).group(1))
            with open(log_file) as f:
                content = f.read()

            # 搜索关键词
            keywords = ["涨价", "地铁", "充值", "交通卡"]
            for kw in keywords:
                if kw in content:
                    self.record_spread(
                        from_agent=0,  # 需要从上下文中推断
                        to_agent=agent_id,
                        time="inferred",
                        context=kw
                    )

    def compute_spread_metrics(self):
        """计算传播指标"""
        metrics = {}

        # 传播广度：最终有多少智能体接收到了信息
        metrics["affected_agents"] = len(self.propagation_graph)

        # 传播速度：信息到达不同比例智能体的时间
        total_agents = 50  # 或从配置读取
        cumulative_count = 0
        for time_point in sorted(self.propagation_graph.keys()):
            cumulative_count += len(self.propagation_graph[time_point])
            pct = cumulative_count / total_agents
            if pct >= 0.5 and "time_to_50pct" not in metrics:
                metrics["time_to_50pct"] = time_point

        return metrics

    def export_graph(self, filepath: str):
        """导出传播图用于可视化"""
        with open(filepath, "w") as f:
            json.dump({
                "propagation_graph": dict(self.propagation_graph),
                "metrics": self.compute_spread_metrics()
            }, f, indent=2)

def main():
    tracker = MisinfoTracker("output/experiments/misinfo_spread/treatment_a")
    tracker.load_from_logs()
    metrics = tracker.compute_spread_metrics()
    print(json.dumps(metrics, indent=2))
    tracker.export_graph("output/experiments/misinfo_spread/treatment_a/spread_graph.json")

if __name__ == "__main__":
    main()
```

---

## 5. 验证方法

### 5.1 数据收集流程

```
Day 1 08:00 → 注入误信息种子
     ↓
每个 Step 记录：
  - 智能体 i 的 misinformation_risk 得分
  - 智能体 i 的对话/反思中是否出现相关关键词
  - 智能体 i 的行为变化（出行选择等）
     ↓
Day 7 → 输出分析报告
```

### 5.2 分析脚本：`experiments/analyze_misinfo.py`

```python
#!/usr/bin/env python3
"""
误信息传播分析脚本

读取实验数据，输出统计报告
"""

import pandas as pd
import json
from pathlib import Path

def analyze_spread_patterns(results_dir: str):
    """分析传播模式"""
    metrics_df = pd.read_csv(f"{results_dir}/intervention/intervention_metrics.csv")

    # 按天聚合
    daily_metrics = metrics_df.groupby("day").agg({
        "misinformation_risk": ["mean", "std", "max"],
        "stance_score": ["mean", "std"],
        "cross_viewpoint_exposure": "mean"
    }).reset_index()

    print("=== 每日误信息风险 ===")
    print(daily_metrics.to_string())

    # 计算传播速度
    days = sorted(metrics_df["day"].unique())
    risk_by_day = metrics_df.groupby("day")["misinformation_risk"].mean()

    print("\n=== 风险变化趋势 ===")
    for day in days:
        change = risk_by_day[day] - risk_by_day[day-1] if day > 1 else 0
        print(f"Day {day}: {risk_by_day[day]:.4f} (change: {change:+.4f})")

def compare_treatments():
    """对比不同实验组"""
    treatments = ["control", "treatment_a", "treatment_b"]
    results = {}

    for treatment in treatments:
        results_dir = f"output/experiments/misinfo_spread/{treatment}"
        try:
            metrics_df = pd.read_csv(f"{results_dir}/intervention/intervention_metrics.csv")
            results[treatment] = {
                "final_misinfo_risk": metrics_df[metrics_df["day"] == metrics_df["day"].max()]["misinformation_risk"].mean(),
                "avg_cross_viewpoint": metrics_df["cross_viewpoint_exposure"].mean(),
                "peak_risk": metrics_df["misinformation_risk"].max()
            }
        except FileNotFoundError:
            results[treatment] = {"error": "Data not found"}

    print("=== 实验组对比 ===")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        analyze_spread_patterns(sys.argv[1])
    else:
        compare_treatments()
```

---

## 6. 预期结果格式

### 6.1 实验日志输出

```
[EXP] Running treatment=treatment_a days=7 seed=42
[EXP] Injecting misinfo seed at Day1 H8, agent=1
[EXP] Running simulation...
[EXP] Analyzing results...
```

### 6.2 指标 CSV 格式

```csv
day,hour,agent_id,misinformation_risk,stance_score,cross_viewpoint_exposure
1,8,1,0.85,0.52,0.15
1,9,1,0.88,0.51,0.14
1,9,2,0.72,0.50,0.18
...
```

### 6.3 传播图 JSON 格式

```json
{
  "propagation_graph": {
    "1": [["Day1H8", "SEED"]],
    "5": [["Day2H10", 1]],
    "12": [["Day3H14", 5]],
    ...
  },
  "metrics": {
    "affected_agents": 32,
    "time_to_50pct": "Day3",
    "final_risk_score": 0.34
  }
}
```

---

## 7. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 实验脚本开发 | 1天 |
| Phase 2 | 预实验（1组，3天） | 1天 |
| Phase 3 | 跑完所有实验组 | 1天 |
| Phase 4 | 数据分析与报告撰写 | 2天 |
| **总计** | | **5天** |

---

## 8. 风险与备选方案

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|---------|
| 传播路径难以追踪 | 中 | 中 | 增强反射关键词匹配 |
| 智能体不响应注入信息 | 低 | 高 | 增大信息强度或改用更"吸引人"的内容 |
| 运行时间过长 | 中 | 中 | 减少天数或减少智能体数量 |

---

## 9. 依赖项

- Python 3.11+
- pandas（数据分析）
- networkx（传播图分析）
- matplotlib（可视化传播过程）

```bash
pip install pandas networkx matplotlib
```