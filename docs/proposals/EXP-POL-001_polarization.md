# 实验提案：观点极化与回音壁效应

**提案编号**：EXP-POL-001
**研究领域**：计算社会科学 / 社会科学
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

算法推荐和社交影响如何导致观点极化？干预措施能否打破回音壁？

### 1.2 研究假设

- **H1**：无干预情况下，相似观点的智能体倾向于聚集，形成回音壁
- **H2**：增加跨观点曝光能减少极化程度
- **H3**：网络同质性（homophily）会加速极化
- **H4**：政策敏感度（policy_sensitivity）高的智能体更容易被极端化

### 1.3 关键指标

| 指标 | 说明 | 测量方式 |
|------|------|---------|
| `stance_score` | 立场得分 | 干预模块输出 |
| `cross_viewpoint_exposure` | 跨观点曝光度 | 干预模块输出 |
| `voice_propensity` | 公共表达倾向 | CSV 初始状态 |
| 群体立场方差 | 智能体间的立场分散程度 | 每日计算 |

---

## 2. GAWorld 已有能力

| 能力 | 对应模块 | 说明 |
|------|---------|------|
| `stance_score` | `intervention_policy.py` | 每 step 记录立场得分 |
| `cross_viewpoint_exposure` | `intervention_policy.py` | 每 step 记录跨观点曝光 |
| 同质性追踪 | `homophily` 状态变量 | 社交网络分析 |
| 对照实验 | CLI `compare-event` | 并行比较有/无干预 |

---

## 3. 实验设计

### 3.1 实验组设计

| 实验组 | 说明 | 关键变量 |
|--------|------|---------|
| Control-baseline | 无干预，自然演化7天 | `intervention.enabled=True` |
| Treatment-diversity | 增强多样性干预 | `cross_viewpoint_exposure` 权重+0.3 |
| Treatment-filter | 过滤相似立场内容 | 减少同质内容推送 |
| Treatment-social | 增强社交多样性 | 优先连接不同立场的智能体 |

### 3.2 初始状态设置

为了研究极化，需要初始化一群立场分化的智能体：

```python
# 在 hangzhou_agents_state_init.csv 中预设立场
# 分成三组：支持(-0.3)、中立(0.0)、反对(+0.3)
STANCE_GROUPS = {
    "pro": [1, 5, 12, 18, 23],      # 支持某政策
    "neutral": [3, 7, 14, 21, 28],   # 中立
    "anti": [2, 9, 15, 20, 27]      # 反对某政策
}
```

### 3.3 信息注入（触发事件）

在 Day 3 注入一个争议性公共议题，触发讨论：

```python
POLICY_EVENT = {
    "name": "交通限行政策",
    "description": "主干道限行导致通勤时间上升并影响出行决策",
    "inject_day": 3,
    "inject_hour": 8,
    "inject_to": "all"  # 广播给所有智能体
}
```

---

## 4. 实施代码

### 4.1 实验脚本：`experiments/polarization_exp.py`

```python
#!/usr/bin/env python3
"""
GAWorld 极化实验

运行方式：
    python experiments/polarization_exp.py run --treatment treatment_diversity --days 14 --seed 42

预期输出：
    output/experiments/polarization/<treatment>/polarization_metrics.csv
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

EXPERIMENT_DIR = Path("output/experiments/polarization")

TREATMENTS = {
    "control_baseline": {
        "description": "无干预，自然演化",
        "intervention_enabled": True,
        "diversity_boost": 0.0,
        "filter_similar": False,
        "social_diversity_boost": False
    },
    "treatment_diversity": {
        "description": "增强多样性干预",
        "intervention_enabled": True,
        "diversity_boost": 0.3,  # cross_viewpoint_exposure 权重增加
        "filter_similar": False,
        "social_diversity_boost": False
    },
    "treatment_filter": {
        "description": "过滤相似立场内容",
        "intervention_enabled": True,
        "diversity_boost": 0.0,
        "filter_similar": True,  # 减少同质内容
        "social_diversity_boost": False
    },
    "treatment_social": {
        "description": "增强社交多样性连接",
        "intervention_enabled": True,
        "diversity_boost": 0.0,
        "filter_similar": False,
        "social_diversity_boost": True  # 优先连接不同立场
    }
}

def setup_initial_state(treatment: str):
    """设置初始状态（如果需要修改 seed 数据）"""
    # 对于极化实验，我们使用预设的立场分组
    # 这里可以修改 config 或创建临时 seed 文件
    pass

def run_treatment(treatment: str, days: int, seed: int):
    """运行单个实验组"""
    config = TREATMENTS[treatment]
    exp_dir = EXPERIMENT_DIR / treatment
    exp_dir.mkdir(parents=True, exist_ok=True)

    # 记录实验配置
    config_record = {
        "treatment": treatment,
        "config": config,
        "days": days,
        "seed": seed,
        "timestamp": datetime.now().isoformat()
    }
    with open(exp_dir / "experiment_config.json", "w") as f:
        json.dump(config_record, f, indent=2)

    # 设置环境变量控制干预参数
    os.environ["GAWORLD_INTERVENTION_ENABLED"] = "true"
    os.environ["GAWORLD_DIVERSITY_BOOST"] = str(config["diversity_boost"])
    os.environ["GAWORLD_FILTER_SIMILAR"] = str(config["filter_similar"]).lower()
    os.environ["GAWORLD_SOCIAL_DIVERSITY"] = str(config["social_diversity_boost"]).lower()

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

def compute_polarization_metrics(exp_dir: Path) -> dict:
    """计算极化指标"""
    metrics_file = exp_dir / "intervention" / "intervention_metrics.csv"

    if not metrics_file.exists():
        return {"error": "Metrics file not found"}

    df = pd.read_csv(metrics_file)

    # 每日极化指标
    daily_polarization = df.groupby("day").agg({
        "stance_score": ["mean", "std", "max", "min"],
        "cross_viewpoint_exposure": "mean",
        "toxicity_score": "mean"
    }).reset_index()

    # 计算极化指数（基于立场方差的标准化度量）
    # Polarization Index = (max - min) / (max + min)，归一化到 [0, 1]
    stance_std_by_day = df.groupby("day")["stance_score"].std()
    stance_range_by_day = df.groupby("day")["stance_score"].agg(lambda x: x.max() - x.min())

    polarization_index = stance_range_by_day / (stance_range_by_day + 1)  # 归一化

    return {
        "treatment": exp_dir.name,
        "final_polarization_index": polarization_index.iloc[-1] if len(polarization_index) > 0 else None,
        "avg_stance_std": stance_std_by_day.mean(),
        "avg_cross_viewpoint_exposure": df["cross_viewpoint_exposure"].mean(),
        "stance_trend": stance_std_by_day.to_dict(),
        "polarization_trend": polarization_index.to_dict()
    }

def analyze_and_compare():
    """分析并对比所有实验组"""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = EXPERIMENT_DIR / treatment
        if exp_dir.exists():
            results[treatment] = compute_polarization_metrics(exp_dir)

    # 输出对比报告
    print("\n=== 极化实验结果对比 ===\n")
    print(f"{'Treatment':<25} {'Final Polarization':<20} {'Avg Std':<15} {'Cross-View':<15}")
    print("-" * 80)
    for treatment, res in results.items():
        if "error" not in res:
            print(f"{treatment:<25} {res.get('final_polarization_index', 'N/A'):<20.4f} "
                  f"{res.get('avg_stance_std', 'N/A'):<15.4f} "
                  f"{res.get('avg_cross_viewpoint_exposure', 'N/A'):<15.4f}")

    # 保存完整结果
    with open(EXPERIMENT_DIR / "comparison_results.json", "w") as f:
        json.dump(results, f, indent=2)

    return results

def plot_polarization_trend():
    """绘制极化趋势图（需要 matplotlib）"""
    try:
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        treatments = list(TREATMENTS.keys())

        for idx, treatment in enumerate(treatments):
            exp_dir = EXPERIMENT_DIR / treatment
            metrics_file = exp_dir / "intervention" / "intervention_metrics.csv"

            if not metrics_file.exists():
                continue

            df = pd.read_csv(metrics_file)

            ax = axes[idx // 2, idx % 2]

            # 立场分布
            daily_std = df.groupby("day")["stance_score"].std()
            ax.plot(daily_std.index, daily_std.values, marker='o')
            ax.set_title(treatment)
            ax.set_xlabel("Day")
            ax.set_ylabel("Stance Std (Polarization)")
            ax.grid(True)

        plt.tight_layout()
        plt.savefig(EXPERIMENT_DIR / "polarization_trends.png", dpi=150)
        print(f"[EXP] Saved plot to {EXPERIMENT_DIR / 'polarization_trends.png'}")

    except ImportError:
        print("[WARN] matplotlib not installed, skipping plot")

def main():
    parser = argparse.ArgumentParser(description="极化实验")
    parser.add_argument("action", choices=["run", "analyze", "compare", "plot"])
    parser.add_argument("--treatment", default="control_baseline",
                        help=f"实验组: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="仿真天数（建议>=14以观察极化）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()

    if args.action == "run":
        run_treatment(args.treatment, args.days, args.seed)
    elif args.action == "analyze":
        exp_dir = EXPERIMENT_DIR / args.treatment
        results = compute_polarization_metrics(exp_dir)
        print(json.dumps(results, indent=2))
    elif args.action == "compare":
        analyze_and_compare()
    elif args.action == "plot":
        plot_polarization_trend()

if __name__ == "__main__":
    main()
```

### 4.2 极化指标计算模块：`experiments/polarization_metrics.py`

```python
#!/usr/bin/env python3
"""
极化指标计算工具

提供多种极化度量方法
"""

import pandas as pd
import numpy as np
from typing import Dict, List
from pathlib import Path

class PolarizationAnalyzer:
    def __init__(self, metrics_df: pd.DataFrame):
        self.df = metrics_df

    def polarization_index(self, stance_col: str = "stance_score") -> pd.Series:
        """
        计算极化指数

        Polarization Index = (max - min) / (max + min)
        范围 [0, 1]，0=完全一致，1=完全对立
        """
        daily_extremes = self.df.groupby("day")[stance_col].agg(["min", "max"])
        diff = daily_extremes["max"] - daily_extremes["min"]
        sum_vals = daily_extremes["max"] + daily_extremes["min"]
        # 避免除零
        sum_vals = sum_vals.replace(0, 0.001)
        return diff / sum_vals

    def stance_variance(self) -> pd.Series:
        """计算每日立场方差"""
        return self.df.groupby("day")["stance_score"].var()

    def bimodality_coefficient(self) -> pd.Series:
        """
        计算双峰性系数

        衡量分布是否接近双峰（两极分化）
        BC > 0.55 通常表示双峰分布
        """
        def calc_bc(group):
            n = len(group)
            if n < 3:
                return 0
            mean = group.mean()
            m3 = ((group - mean) ** 3).mean()  # 三阶矩
            m2 = ((group - mean) ** 2).mean()  # 方差
            if m2 == 0:
                return 0
            skew = m3 / (m2 ** 1.5)
            kurt = ((group - mean) ** 4).mean() / (m2 ** 2) if m2 > 0 else 0
            bc = (skew ** 2 + 1) / (kurt + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))
            return bc

        return self.df.groupby("day")["stance_score"].apply(calc_bc)

    def exposure_diversity_index(self) -> pd.Series:
        """
        计算曝光多样性指数

        cross_viewpoint_exposure 越高表示接触的观点越多样
        """
        return self.df.groupby("day")["cross_viewpoint_exposure"].mean()

    def group_stance_divergence(self, groups: Dict[str, List[int]]) -> pd.DataFrame:
        """
        计算不同组之间的立场差异

        groups: {"group_name": [agent_ids]}
        """
        results = {}
        for group_name, agent_ids in groups.items():
            group_data = self.df[self.df["agent_id"].isin(agent_ids)]
            results[group_name] = group_data.groupby("day")["stance_score"].mean()

        divergence = pd.DataFrame(results)
        divergence["group_std"] = divergence.std(axis=1)
        return divergence

    def generate_report(self) -> Dict:
        """生成完整的极化分析报告"""
        return {
            "polarization_index": self.polarization_index().to_dict(),
            "stance_variance": self.stance_variance().to_dict(),
            "bimodality_coefficient": self.bimodality_coefficient().to_dict(),
            "exposure_diversity": self.exposure_diversity_index().to_dict(),
            "summary": {
                "final_polarization": self.polarization_index().iloc[-1] if len(self.polarization_index()) > 0 else None,
                "max_polarization": self.polarization_index().max() if len(self.polarization_index()) > 0 else None,
                "avg_exposure_diversity": self.exposure_diversity_index().mean()
            }
        }

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python polarization_metrics.py <metrics.csv>")
        sys.exit(1)

    df = pd.read_csv(sys.argv[1])
    analyzer = PolarizationAnalyzer(df)
    report = analyzer.generate_report()

    import json
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
```

---

## 5. 实验流程

```
Day 1-2: 基线期（观察自然立场分布）
     ↓
Day 3: 注入争议政策事件
     ↓
Day 4-14: 观察极化动态
     ↓
输出：极化趋势图、组间对比、干预效果评估
```

---

## 6. 预期结果格式

### 6.1 极化指标时间序列

```csv
day,polarization_index,stance_std,cross_viewpoint_exposure
1,0.12,0.08,0.45
2,0.15,0.09,0.43
3,0.28,0.15,0.38  # 注入事件后极化上升
4,0.35,0.18,0.35
...
14,0.52,0.22,0.25  # 极化继续加剧
```

### 6.2 组间对比报告

```json
{
  "control_baseline": {
    "final_polarization_index": 0.52,
    "avg_stance_std": 0.18,
    "avg_cross_viewpoint_exposure": 0.25
  },
  "treatment_diversity": {
    "final_polarization_index": 0.31,
    "avg_stance_std": 0.12,
    "avg_cross_viewpoint_exposure": 0.52
  },
  "treatment_filter": {...},
  "treatment_social": {...}
}
```

---

## 7. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 脚本开发 + 预实验 | 2天 |
| Phase 2 | 运行全部4组实验（各14天） | 2天 |
| Phase 3 | 数据分析与可视化 | 2天 |
| Phase 4 | 报告撰写 | 1天 |
| **总计** | | **7天** |

---

## 8. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| 回音壁效应 | Pariser (2011) *The Filter Bubble* | 量化干预对打破回音壁的效果 |
| 极化动力学 | Lelkes et al. (2019) | 提供微观机制（智能体交互）层面的解释 |
| 推荐系统干预 | Anderson et al. (2020) | 评估不同干预策略的有效性 |

---

## 9. 扩展方向

### 9.1 长期极化研究

运行 30+ 天，观察极化是否自我强化或达到平衡

### 9.2 多议题极化

同时注入多个争议议题，观察智能体是否对不同议题保持一致立场

### 9.3 跨议题态度一致性

研究支持某政策的智能体是否也倾向于支持相关政策（态度一致性）