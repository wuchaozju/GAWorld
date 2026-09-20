# 实验提案：政策事件对照实验框架

**提案编号**：EXP-POLICY-001
**研究领域**：政策科学 / 公共管理 / 计算社会科学
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

如何系统性地评估政策（如交通限行、补贴、限购）对城市居民行为和社会指标的影响？

### 1.2 研究假设

- **H1**：政策效果因居民收入水平、职业类型而异（异质性效应）
- **H2**：政策效果随时间衰减或增强
- **H3**：多重政策组合可能产生非线性交互效应
- **H4**：政策效果可以通过干预指标（立场、毒性、误信息风险）预测

### 1.3 GAWorld 的 compare-event 功能

GAWorld 已内置 `compare-event` CLI 命令，可并行运行"有政策"和"无政策"两条路径：

```bash
python generative_city_sim.py compare-event \
  --event-name "临时交通限行" \
  --event-description "主干道限行导致通勤时间上升并影响出行决策" \
  --event-day 2 \
  --event-time 09:00 \
  --sim-days 3 \
  --llm-provider openai_gpt \
  --seed 42
```

---

## 2. 政策实验设计模板

### 2.1 政策类型矩阵

| 政策类别 | 具体政策 | 测量指标 |
|---------|---------|---------|
| 交通政策 | 限行、拥堵费、地铁调价 | 出行方式、通勤成本、情绪 |
| 住房政策 | 购房补贴、租房券、限购 | 消费结构、储蓄率、压力 |
| 就业政策 | 培训补贴、失业救济、最低工资 | 收入、econ_security、emotion |
| 环境政策 | 垃圾分类、限塑、碳税 | 消费结构、出行选择 |
| 社会政策 | 医疗补贴、教育投入、养老金 | 支出结构、emotion、stress |

### 2.2 对照实验设计

每项政策实验包含：

```
Policy Experiment: <Policy_Name>
├── Control: 无政策基线运行 (N days)
├── Treatment: 有政策运行 (N days)
└── Comparison: delta metrics
```

### 2.3 测量指标体系

**行为指标**：
- 出行方式选择（公交/地铁/出租/自驾）
- 消费结构变化（8大消费类目）
- 社交网络变化（网络密度、关系强度）

**主观指标**：
- emotion（情绪）
- stress（压力）
- econ_security（经济安全感）
- city_identity（城市认同）

**政策专项指标**：
- 政策感知度（policy_sensitivity 高者更敏感）
- 政策支持度（通过访谈测量）
- 政策遵从度（实际行为是否响应政策）

---

## 3. 实施代码

### 3.1 政策实验运行器：`experiments/policy_experiment.py`

```python
#!/usr/bin/env python3
"""
GAWorld 政策实验框架

运行方式：
    python experiments/policy_experiment.py run --policy traffic_restriction --days 14 --seed 42

预期输出：
    output/experiments/policy/<policy_name>/comparison_summary.md
    output/experiments/policy/<policy_name>/comparison_metrics.csv
"""

import argparse
import json
import subprocess
import sys
import shutil
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

EXPERIMENT_DIR = Path("output/experiments/policy")

# 预定义政策实验
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

def run_policy_experiment(policy_name: str, days: int, seed: int) -> dict:
    """运行单个政策实验"""
    if policy_name not in POLICY_CONFIGS:
        print(f"[ERROR] Unknown policy: {policy_name}")
        return {"error": f"Policy {policy_name} not found in configs"}

    config = POLICY_CONFIGS[policy_name]
    exp_dir = EXPERIMENT_DIR / policy_name
    exp_dir.mkdir(parents=True, exist_ok=True)

    # 记录实验配置
    experiment_record = {
        "policy_name": policy_name,
        "config": config,
        "days": days,
        "seed": seed,
        "timestamp": datetime.now().isoformat()
    }
    with open(exp_dir / "experiment_config.json", "w") as f:
        json.dump(experiment_record, f, indent=2, ensure_ascii=False)

    # 使用 compare-event 运行
    cmd = [
        "python", "generative_city_sim.py", "compare-event",
        "--event-name", config["event_name"],
        "--event-description", config["event_description"],
        "--event-day", str(config["event_day"]),
        "--event-time", config["event_time"],
        "--sim-days", str(days),
        "--seed", str(seed),
        "--llm-provider", "openai_gpt"  # 可配置
    ]

    print(f"[EXP] Running policy experiment: {policy_name}")
    print(f"[EXP] Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent.parent)

    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}", file=sys.stderr)
        return {"error": result.stderr}

    return {"status": "success", "output_dir": str(exp_dir)}

def analyze_policy_effects(policy_name: str) -> dict:
    """分析政策效果"""
    exp_dir = EXPERIMENT_DIR / policy_name

    comparison_dir = exp_dir / "comparisons"
    if not comparison_dir.exists():
        # 查找实际的比较结果目录
        for subdir in exp_dir.iterdir():
            if subdir.is_dir() and "comparisons" in subdir.name:
                comparison_dir = subdir
                break

    if not comparison_dir.exists():
        return {"error": "Comparison results not found"}

    # 查找 comparison_summary.md
    summary_files = list(comparison_dir.glob("**/comparison_summary.md"))
    if summary_files:
        with open(summary_files[0]) as f:
            summary_content = f.read()
    else:
        summary_content = None

    # 查找 comparison_metrics.csv
    metrics_files = list(comparison_dir.glob("**/comparison_metrics.csv"))
    if metrics_files:
        metrics_df = pd.read_csv(metrics_files[0])
    else:
        metrics_df = None

    results = {
        "policy_name": policy_name,
        "has_summary": summary_content is not None,
        "has_metrics": metrics_df is not None
    }

    if metrics_df is not None:
        # 计算政策效果
        if "event_baseline_delta" in metrics_df.columns or "delta" in metrics_df.columns:
            delta_col = "event_baseline_delta" if "event_baseline_delta" in metrics_df.columns else "delta"
            results["avg_delta"] = metrics_df[delta_col].mean() if delta_col in metrics_df.columns else None
            results["significant_metrics"] = find_significant_changes(metrics_df)

    # 读取 with_event 和 without_event 的状态对比
    with_event_dir = comparison_dir / "with_event"
    without_event_dir = comparison_dir / "without_event"

    if with_event_dir.exists() and without_event_dir.exists():
        with_state = pd.read_csv(with_event_dir / "state" / "agent_state_history.csv")
        without_state = pd.read_csv(without_event_dir / "state" / "agent_state_history.csv")

        # 计算各指标的差异
        subjective_metrics = ["emotion", "stress", "econ_security", "city_identity"]

        effect_summary = {}
        for metric in subjective_metrics:
            if metric in with_state.columns and metric in without_state.columns:
                with_mean = with_state.groupby("day")[metric].mean()
                without_mean = without_state.groupby("day")[metric].mean()

                effect_summary[metric] = {
                    "with_policy_mean": float(with_mean.mean()),
                    "without_policy_mean": float(without_mean.mean()),
                    "avg_effect": float((with_mean - without_mean).mean()),
                    "day_by_day": {
                        f"day_{d}": {
                            "with": float(with_mean.get(d, 0)),
                            "without": float(without_mean.get(d, 0)),
                            "delta": float(with_mean.get(d, 0) - without_mean.get(d, 0))
                        }
                        for d in with_mean.index if d in without_mean.index
                    }
                }

        results["subjective_effects"] = effect_summary

    return results

def find_significant_changes(metrics_df: pd.DataFrame) -> list:
    """找出显著变化的指标"""
    significant = []

    # 简化：找出 delta 绝对值大于 0.1 的指标
    for col in metrics_df.columns:
        if "delta" in col.lower() or col.endswith("_change"):
            avg_abs_delta = metrics_df[col].abs().mean()
            if avg_abs_delta > 0.1:
                significant.append({
                    "metric": col,
                    "avg_abs_delta": float(avg_abs_delta)
                })

    return significant

def generate_policy_report(policy_name: str):
    """生成政策实验报告"""
    results = analyze_policy_effects(policy_name)

    report_lines = []
    report_lines.append(f"# 政策实验报告：{policy_name}\n")
    report_lines.append(f"生成时间：{datetime.now().isoformat()}\n")

    if "error" in results:
        report_lines.append(f"\n[ERROR] {results['error']}\n")
        return "\n".join(report_lines)

    # 主观指标效果
    if "subjective_effects" in results:
        report_lines.append("## 主观指标变化\n")
        report_lines.append("| 指标 | 有政策均值 | 无政策均值 | 平均效果 |")
        report_lines.append("|------|-----------|-----------|---------|")

        for metric, data in results["subjective_effects"].items():
            avg_effect = data["avg_effect"]
            effect_sign = "+" if avg_effect > 0 else ""
            report_lines.append(f"| {metric} | {data['with_policy_mean']:.3f} "
                             f"| {data['without_policy_mean']:.3f} "
                             f"| {effect_sign}{avg_effect:.3f} |")

    # 显著变化指标
    if "significant_metrics" in results:
        report_lines.append("\n## 显著变化的指标\n")
        for item in results["significant_metrics"]:
            report_lines.append(f"- {item['metric']}: avg |delta| = {item['avg_abs_delta']:.4f}")

    report_text = "\n".join(report_lines)
    print(report_text)

    # 保存报告
    exp_dir = EXPERIMENT_DIR / policy_name
    with open(exp_dir / "policy_report.md", "w") as f:
        f.write(report_text)

    return report_text

def compare_policies():
    """对比所有政策实验"""
    all_results = {}

    for policy_name in POLICY_CONFIGS.keys():
        exp_dir = EXPERIMENT_DIR / policy_name
        if exp_dir.exists():
            all_results[policy_name] = analyze_policy_effects(policy_name)

    import json
    print(json.dumps(all_results, indent=2, ensure_ascii=False))

    with open(EXPERIMENT_DIR / "all_policies_comparison.json", "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    return all_results

def main():
    parser = argparse.ArgumentParser(description="政策实验框架")
    parser.add_argument("action", choices=["run", "analyze", "report", "compare"])
    parser.add_argument("--policy", default="traffic_restriction",
                        help=f"政策: {', '.join(POLICY_CONFIGS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="仿真天数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()

    if args.action == "run":
        run_policy_experiment(args.policy, args.days, args.seed)
    elif args.action == "analyze":
        results = analyze_policy_effects(args.policy)
        import json
        print(json.dumps(results, indent=2))
    elif args.action == "report":
        generate_policy_report(args.policy)
    elif args.action == "compare":
        compare_policies()

if __name__ == "__main__":
    main()
```

### 3.2 异质性分析模块：`experiments/policy_heterogeneity.py`

```python
#!/usr/bin/env python3
"""
政策效果异质性分析

分析政策效果是否因智能体特征（收入、职业、性格）而异
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json

class PolicyHeterogeneityAnalyzer:
    def __init__(self, exp_dir: Path):
        self.exp_dir = exp_dir

    def load_data(self):
        """加载实验数据"""
        comparison_dir = self.exp_dir / "comparisons"

        with_event_dir = comparison_dir / "with_event"
        without_event_dir = comparison_dir / "without_event"

        with_state = pd.read_csv(with_event_dir / "state" / "agent_state_history.csv")
        without_state = pd.read_csv(without_event_dir / "state" / "agent_state_history.csv")

        # 加载初始状态以获取智能体特征
        init_state = pd.read_csv(Path("data/hangzhou_agents_state_init.csv"))

        return with_state, without_state, init_state

    def compute_policy_effect_by_group(self, with_state: pd.DataFrame,
                                       without_state: pd.DataFrame,
                                       init_state: pd.DataFrame,
                                       group_by: str) -> pd.DataFrame:
        """
        按分组变量计算政策效果

        group_by: income_level, age_group, gender, risk_preference, etc.
        """
        # 根据 group_by 创建分组
        if group_by == "income_level":
            # 从 init_state 获取收入等级
            init_state["income_level"] = pd.qcut(
                init_state.groupby("agent_id")["income"].transform("mean") if "income" in init_state.columns
                else init_state["id"],
                q=3, labels=["Low", "Medium", "High"]
            )
            group_col = "income_level"
        else:
            group_col = group_by if group_by in init_state.columns else None

        if group_col is None or group_col not in init_state.columns:
            return None

        # 计算每个智能体的政策效果（with - without）
        subjective_metrics = ["emotion", "stress", "econ_security"]

        effects = {}
        for metric in subjective_metrics:
            if metric in with_state.columns and metric in without_state.columns:
                with_daily = with_state.groupby(["agent_id", "day"])[metric].mean()
                without_daily = without_state.groupby(["agent_id", "day"])[metric].mean()

                # 计算差值
                effect = (with_daily - without_daily).reset_index()
                effect.columns = ["agent_id", "day", f"effect_{metric}"]

                # 合并分组信息
                effect = effect.merge(init_state[["id", group_col]],
                                     left_on="agent_id", right_on="id")

                effects[metric] = effect

        return effects

    def analyze_heterogeneity(self, group_by: str = "income_level") -> dict:
        """
        分析政策效果的异质性

        输出：哪些群体受政策影响最大/最小
        """
        with_state, without_state, init_state = self.load_data()

        effects = self.compute_policy_effect_by_group(
            with_state, without_state, init_state, group_by
        )

        if not effects:
            return {"error": "Failed to compute effects"}

        results = {}

        for metric, effect_df in effects.items():
            if effect_df is None:
                continue

            # 按组计算平均效果
            group_effects = effect_df.groupby(group_by)[f"effect_{metric}"].agg([
                "mean", "std", "count"
            ]).reset_index()

            results[metric] = group_effects.to_dict()

        return results

    def identify_most_affected_groups(self) -> dict:
        """识别受政策影响最大的群体"""
        results = {}

        for group_by in ["income_level", "risk_preference", "platform_dependence"]:
            heterogeneity = self.analyze_heterogeneity(group_by)
            results[group_by] = heterogeneity

        # 汇总：找出在所有维度上都受强烈影响的智能体
        all_agents = set()
        for group_data in results.values():
            for metric, data in group_data.items():
                if isinstance(data, dict) and "mean" in data:
                    # 找出 mean > 0 的组
                    for i, mean_val in enumerate(data["mean"]):
                        if abs(mean_val) > 0.05:  # 阈值
                            # 获取该组的智能体
                            pass  # 需要更详细的逻辑

        return results

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python policy_heterogeneity.py <exp_dir>")
        sys.exit(1)

    exp_dir = Path(sys.argv[1])
    analyzer = PolicyHeterogeneityAnalyzer(exp_dir)

    # 分析各维度的异质性
    for group_by in ["income_level", "risk_preference"]:
        print(f"\n=== Heterogeneity by {group_by} ===")
        results = analyzer.analyze_heterogeneity(group_by)
        import json
        print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

---

## 4. 预定义政策实验清单

### 4.1 短期可执行政策实验（1-2天）

| 政策 | 命令 | 预期发现 |
|------|------|---------|
| 交通限行 | `python experiments/policy_experiment.py run --policy traffic_restriction` | 出行方式改变、stress上升 |
| 住房补贴 | `python experiments/policy_experiment.py run --policy housing_subsidy` | 购房意愿增加、econ_security提升 |
| 医疗改革 | `python experiments/policy_experiment.py run --policy medical_reform` | 就医频率变化、emotion改善 |

### 4.2 中期政策实验（3-5天）

| 政策 | 说明 | 扩展方向 |
|------|------|---------|
| 失业培训 | 增加 job_training 政策实验 | 分析不同职业的参训效果 |
| 环境政策 | 增加 carbon_tax 碳税实验 | 分析对消费结构的影响 |
| 组合政策 | 测试"交通限行+住房补贴"组合 | 评估政策交互效应 |

---

## 5. 输出格式

### 5.1 对比摘要

```markdown
# 对比实验摘要

## 政策：临时交通限行

### 主观指标变化（有事件 vs 无事件）

| 指标 | 有政策 | 无政策 | 差异 | 变化方向 |
|------|--------|--------|------|---------|
| emotion | 0.56 | 0.58 | -0.02 | ↓ |
| stress | 0.52 | 0.48 | +0.04 | ↑ |
| econ_security | 0.54 | 0.56 | -0.02 | ↓ |

### 干预指标变化

| 指标 | 有政策 | 无政策 | 差异 |
|------|--------|--------|------|
| stance_score | 0.45 | 0.44 | +0.01 |
| cross_viewpoint_exposure | 0.38 | 0.40 | -0.02 |
```

### 5.2 异质性分析表

```csv
group_by,income_level,metric,mean_effect,std
Low,Low,emotion,-0.03,0.05
Low,Medium,emotion,-0.02,0.04
Low,High,emotion,-0.01,0.03
```

---

## 6. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 框架开发 | 1天 |
| Phase 2 | 运行3个预定义政策实验 | 1天 |
| Phase 3 | 异质性分析 | 1天 |
| Phase 4 | 报告撰写 | 1天 |
| **总计** | | **4天** |

---

## 7. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| 政策评估 | Wooldridge (2010) *Econometric Analysis of Cross Section* | 提供微观政策效果估计 |
| 异质性处理效应 | Angrist & Pischke (2009) *Mostly Harmless Econometrics* | 量化政策在群体间的差异 |
| 政策组合效应 | Stiglitz (2012) *The Price of Inequality* | 评估多重政策的交互效应 |

---

## 8. 扩展方向

### 8.1 长期政策效果追踪

运行60+天，观察政策效果的衰减或强化

### 8.2 政策时序设计

测试"政策A先实施，政策B后实施"的顺序效果

### 8.3 政策强度梯度

同一政策设置不同强度（低/中/高），分析剂量-效应关系