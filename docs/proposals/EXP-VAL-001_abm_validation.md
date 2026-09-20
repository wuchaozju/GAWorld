# 实验提案：ABM（多智能体仿真）验证框架

**提案编号**：EXP-VAL-001
**研究领域**：方法论 / 计算社会科学
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

如何验证计算社会仿真模型的合理性？仿真结果与现实数据的差距如何量化？模型的适用范围和局限性在哪里？

### 1.2 研究假设

- **H1**：GAWorld 的关键行为模式（出行选择、消费结构）与真实城市数据趋势一致
- **H2**：模型的误差主要集中在极端情况（如金融危机、自然灾害）
- **H3**：通过参数校准可以显著提高模型与真实数据的拟合度
- **H4**：不同智能体类型（收入、年龄）的行为模式差异可以被模型捕捉

### 1.3 验证框架

```
┌─────────────────────────────────────────────┐
│           ABM 验证框架                        │
│                                             │
│   真实数据 ←→ 仿真输出                       │
│       ↓              ↓                      │
│   参考基准      模型预测                      │
│       ↓              ↓                      │
│   误差量化 ←→ 参数校准                       │
│       ↓              ↓                      │
│   模型改进 ←→ 再验证                         │
└─────────────────────────────────────────────┘
```

---

## 2. GAWorld 可验证的行为维度

### 2.1 可对比的行为指标

| 行为维度 | GAWorld 输出 | 现实数据来源 |
|---------|-------------|-------------|
| 出行方式结构 | 公交/地铁/出租/自驾比例 | 城市交通调查 |
| 恩格尔系数 | 食品支出/总消费 | 统计年鉴家庭调查 |
| 储蓄率 | 储蓄/可支配收入 | 家庭金融调查 |
| 社交网络规模 | 平均连接数、联系频率 | 社会网络调查 |
| 情绪分布 | 平均情绪、压力水平 | 心理健康调查 |
| 通勤时间 | 平均通勤时长 | 城市交通报告 |

### 2.2 参考基准数据

```python
# 参考基准（杭州/中国城市平均值，需要从公开数据获取）
REFERENCE_BENCHMARKS = {
    "transport_mode_share": {
        "bus": 0.25,
        "metro": 0.35,
        "taxi": 0.10,
        "car": 0.20,
        "bike/walk": 0.10
    },
    "engels_coefficient": {
        "low_income": 0.48,   # < 2000 CNY/month
        "middle_income": 0.35,  # 2000-5000
        "high_income": 0.22    # > 5000
    },
    "savings_rate": {
        "low_income": 0.05,
        "middle_income": 0.20,
        "high_income": 0.35
    },
    "commute_time_minutes": {
        "mean": 45,
        "std": 20
    },
    "social_network_size": {
        "mean": 150,
        "median": 80
    }
}
```

---

## 3. 实施代码

### 3.1 验证框架主脚本：`experiments/abm_validation_framework.py`

```python
#!/usr/bin/env python3
"""
GAWorld ABM 验证框架

运行方式：
    python experiments/abm_validation_framework.py validate --metric transport_mode

预期输出：
    output/experiments/abm_validation/<metric>/validation_report.md
    output/experiments/abm_validation/<metric>/error_analysis.csv
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

EXPERIMENT_DIR = Path("output/experiments/abm_validation")

# 参考基准数据（需要根据真实数据填充）
REFERENCE_BENCHMARKS = {
    "transport_mode_share": {
        "bus": 0.25,
        "metro": 0.35,
        "taxi": 0.10,
        "car": 0.20,
        "bike_walk": 0.10
    },
    "engels_coefficient": {
        "low_income": 0.48,
        "middle_income": 0.35,
        "high_income": 0.22
    },
    "savings_rate": {
        "low_income": 0.05,
        "middle_income": 0.20,
        "high_income": 0.35
    },
    "emotion_distribution": {
        "mean": 0.60,
        "std": 0.15
    }
}

METRIC_CONFIGS = {
    "transport_mode": {
        "description": "出行方式结构验证",
        "output_file": "transport_mode_share.csv",
        "reference_key": "transport_mode_share",
        "simulation_data_extractor": extract_transport_mode_data,
        "error_metric": "KL_divergence"
    },
    "engels_coefficient": {
        "description": "恩格尔系数验证",
        "output_file": "engels_coefficient.csv",
        "reference_key": "engels_coefficient",
        "simulation_data_extractor": extract_engels_data,
        "error_metric": "relative_error"
    },
    "savings_rate": {
        "description": "储蓄率验证",
        "output_file": "savings_rate.csv",
        "reference_key": "savings_rate",
        "simulation_data_extractor": extract_savings_data,
        "error_metric": "absolute_error"
    },
    "emotion_distribution": {
        "description": "情绪分布验证",
        "output_file": "emotion_distribution.csv",
        "reference_key": "emotion_distribution",
        "simulation_data_extractor": extract_emotion_data,
        "error_metric": "wasserstein_distance"
    }
}

def run_simulation_for_validation(days: int = 30, seed: int = 42) -> bool:
    """运行仿真用于验证"""
    exp_dir = EXPERIMENT_DIR / "simulation_output"
    exp_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python", "generative_city_sim.py", "run",
        "--sim-days", str(days),
        "--seed", str(seed),
        "--output-dir", str(exp_dir)
    ]

    print(f"[EXP] Running simulation for validation: days={days}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    return result.returncode == 0

def extract_transport_mode_data(exp_dir: Path) -> dict:
    """提取出行方式数据"""
    state_file = exp_dir / "state" / "agent_state_history.csv"
    if not state_file.exists():
        return {}

    df = pd.read_csv(state_file)

    # 从活动列推断交通方式
    mode_counts = {
        "bus": 0,
        "metro": 0,
        "taxi": 0,
        "car": 0,
        "bike_walk": 0,
        "other": 0
    }

    for activity in df["activity"].dropna():
        activity_lower = activity.lower()
        if "公交" in activity or "bus" in activity_lower:
            mode_counts["bus"] += 1
        elif "地铁" in activity or "metro" in activity_lower:
            mode_counts["metro"] += 1
        elif "出租" in activity or "taxi" in activity_lower:
            mode_counts["taxi"] += 1
        elif "自驾" in activity or "car" in activity_lower:
            mode_counts["car"] += 1
        elif "步行" in activity or "自行车" in activity or "walk" in activity_lower or "bike" in activity_lower:
            mode_counts["bike_walk"] += 1
        else:
            mode_counts["other"] += 1

    total = sum(mode_counts.values())
    mode_share = {k: v / total if total > 0 else 0 for k, v in mode_counts.items()}

    return mode_share

def extract_engels_data(exp_dir: Path) -> dict:
    """提取恩格尔系数数据"""
    economy_dir = exp_dir / "economy"
    if not economy_dir.exists():
        return {}

    # 从 daily_ledger 获取消费数据
    ledger_file = economy_dir / "daily_ledger.csv"
    if not ledger_file.exists():
        return {}

    df = pd.read_csv(ledger_file)

    # 按收入分组计算恩格尔系数
    # 这里需要知道收入信息，简化处理
    df["engels"] = df["food_expense"] / df["total_consumption"] if "total_consumption" in df.columns else None

    return {
        "mean_engels": df["engels"].mean() if "engels" in df.columns else None,
        "std_engels": df["engels"].std() if "engels" in df.columns else None
    }

def extract_savings_data(exp_dir: Path) -> dict:
    """提取储蓄率数据"""
    economy_dir = exp_dir / "economy"
    if not economy_dir.exists():
        return {}

    ledger_file = economy_dir / "daily_ledger.csv"
    if not ledger_file.exists():
        return {}

    df = pd.read_csv(ledger_file)

    savings_rate = (df["savings"] / df["income"]).mean() if "savings" in df.columns and "income" in df.columns else None

    return {"mean_savings_rate": savings_rate}

def extract_emotion_data(exp_dir: Path) -> dict:
    """提取情绪分布数据"""
    state_file = exp_dir / "state" / "agent_state_history.csv"
    if not state_file.exists():
        return {}

    df = pd.read_csv(state_file)

    return {
        "mean": df["emotion"].mean(),
        "std": df["emotion"].std(),
        "min": df["emotion"].min(),
        "max": df["emotion"].max()
    }

def compute_kl_divergence(p: dict, q: dict) -> float:
    """计算 KL 散度 D(P||Q)"""
    total = 0
    for key in p:
        if key in q and q[key] > 0 and p[key] > 0:
            total += p[key] * np.log(p[key] / q[key])

    return total

def compute_wasserstein_distance(sim_dist: dict, ref_dist: dict) -> float:
    """计算 Wasserstein 距离（用于分布比较）"""
    # 简化：假设两个分布都是离散的，使用欧氏距离
    all_keys = set(sim_dist.keys()) | set(ref_dist.keys())

    p_vals = [sim_dist.get(k, 0) for k in all_keys]
    q_vals = [ref_dist.get(k, 0) for k in all_keys]

    return np.sqrt(sum((a - b) ** 2 for a, b in zip(p_vals, q_vals)))

def compute_relative_error(sim_value: float, ref_value: float) -> float:
    """计算相对误差"""
    if ref_value == 0:
        return float('inf')
    return abs(sim_value - ref_value) / abs(ref_value)

def validate_metric(metric_name: str) -> dict:
    """验证单个指标"""
    if metric_name not in METRIC_CONFIGS:
        return {"error": f"Unknown metric: {metric_name}"}

    config = METRIC_CONFIGS[metric_name]
    exp_dir = EXPERIMENT_DIR / "simulation_output"
    ref_dir = EXPERIMENT_DIR / "reference"

    # 提取仿真数据
    sim_data = config["simulation_data_extractor"](exp_dir)

    # 获取参考基准
    reference = REFERENCE_BENCHMARKS.get(config["reference_key"], {})

    # 计算误差
    error_metric = config["error_metric"]

    if error_metric == "KL_divergence":
        error = compute_kl_divergence(sim_data, reference)
        error_type = "KL divergence"
    elif error_metric == "relative_error":
        # 对于单一值的情况
        sim_value = sim_data.get("mean_engels") or sim_data.get("mean_savings_rate")
        ref_value = list(reference.values())[0] if reference else None
        error = compute_relative_error(sim_value, ref_value) if sim_value and ref_value else None
        error_type = "relative error"
    elif error_metric == "wasserstein_distance":
        error = compute_wasserstein_distance(sim_data, reference)
        error_type = "Wasserstein distance"
    else:
        error = None
        error_type = "unknown"

    return {
        "metric": metric_name,
        "simulation_data": sim_data,
        "reference_data": reference,
        "error": error,
        "error_type": error_type
    }

def run_full_validation() -> dict:
    """运行完整验证"""
    results = {}

    for metric_name in METRIC_CONFIGS.keys():
        print(f"[EXP] Validating {metric_name}...")
        results[metric_name] = validate_metric(metric_name)

    return results

def generate_validation_report(results: dict) -> str:
    """生成验证报告"""
    report_lines = []
    report_lines.append("# ABM 验证报告\n")
    report_lines.append(f"生成时间：{datetime.now().isoformat()}\n")

    report_lines.append("## 验证结果摘要\n")

    for metric_name, result in results.items():
        if "error" in result:
            report_lines.append(f"\n### {metric_name}: ERROR - {result['error']}\n")
            continue

        report_lines.append(f"\n### {metric_name}\n")
        report_lines.append(f"- 误差类型：{result['error_type']}\n")
        report_lines.append(f"- 误差值：{result['error']:.4f}\n")

        # 仿真数据 vs 参考数据
        report_lines.append("\n对比：\n")
        report_lines.append("| 维度 | 仿真值 | 参考值 | 差异 |\n")
        report_lines.append("|------|--------|--------|------|\n")

        sim_data = result.get("simulation_data", {})
        ref_data = result.get("reference_data", {})

        if isinstance(sim_data, dict) and isinstance(ref_data, dict):
            all_keys = set(sim_data.keys()) | set(ref_data.keys())
            for key in sorted(all_keys):
                sim_val = sim_data.get(key, "N/A")
                ref_val = ref_data.get(key, "N/A")
                if isinstance(sim_val, float) and isinstance(ref_val, float):
                    diff = sim_val - ref_val
                    diff_sign = "+" if diff > 0 else ""
                    report_lines.append(f"| {key} | {sim_val:.4f} | {ref_val:.4f} | {diff_sign}{diff:.4f} |\n")
                else:
                    report_lines.append(f"| {key} | {sim_val} | {ref_val} | - |\n")

    report_text = "".join(report_lines)
    print(report_text)

    # 保存报告
    report_dir = EXPERIMENT_DIR / "validation_reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    with open(report_dir / "validation_report.md", "w") as f:
        f.write(report_text)

    return report_text

def calibrate_parameters():
    """参数校准（简化版）"""
    # 这是个简化框架，实际需要使用优化算法如 scipy.optimize
    print("[EXP] Parameter calibration not yet implemented")

    # 参数调整方向建议
    calibration_suggestions = {
        "transport_mode": {
            "metro_sensitivity": "+0.1 if metro too low",
            "car_cost_weight": "+0.15 if car too high",
            "rush_hour_multiplier": "+0.05 if peak too sharp"
        },
        "engels_coefficient": {
            "food_elasticity": "-0.05 if engels too high",
            "income_growth_rate": "+0.1 if middle class consumption too low"
        },
        "savings_rate": {
            "savings_rate_target": "-0.05 if savings too high",
            "investment_return_rate": "+0.02 if investment income too low"
        }
    }

    with open(EXPERIMENT_DIR / "calibration_suggestions.json", "w") as f:
        json.dump(calibration_suggestions, f, indent=2)

    return calibration_suggestions

def main():
    parser = argparse.ArgumentParser(description="ABM验证框架")
    parser.add_argument("action", choices=["run", "validate", "report", "calibrate"])
    parser.add_argument("--metric", help="验证特定指标")
    parser.add_argument("--days", type=int, default=30, help="仿真天数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()

    if args.action == "run":
        run_simulation_for_validation(args.days, args.seed)
    elif args.action == "validate":
        if args.metric:
            result = validate_metric(args.metric)
            print(json.dumps(result, indent=2))
        else:
            results = run_full_validation()
            print(json.dumps(results, indent=2))
    elif args.action == "report":
        if args.metric:
            result = validate_metric(args.metric)
        else:
            results = run_full_validation()
            result = {"all_metrics": results}
        generate_validation_report(result)
    elif args.action == "calibrate":
        calibrate_parameters()

if __name__ == "__main__":
    main()
```

### 3.2 参数敏感度分析：`experiments/sensitivity_analysis.py`

```python
#!/usr/bin/env python3
"""
参数敏感度分析

测量模型输出对参数变化的敏感程度
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

EXPERIMENT_DIR = Path("output/experiments/sensitivity")

# 待分析的参数及其范围
PARAM_RANGES = {
    "economy.tax.monthly_exemption": [3000, 5000, 7000],
    "economy.social_insurance.pension_rate": [0.06, 0.08, 0.10],
    "intervention.enabled": [True, False],
    "dynamic_behavior.enabled": [True, False],
    "interests.enabled": [True, False],
    "llm.temperature": [0.3, 0.7, 1.0]
}

def run_sensitivity_analysis(param_name: str, param_values: list) -> dict:
    """对单个参数进行敏感度分析"""
    results = []

    for value in param_values:
        print(f"[EXP] Testing {param_name}={value}")

        # 设置环境变量
        import os
        os.environ[f"GAWORLD_{param_name.upper().replace('.', '_')}"] = str(value)

        # 运行仿真
        exp_dir = EXPERIMENT_DIR / f"sensitivity_{param_name}_{value}"
        exp_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "python", "generative_city_sim.py", "run",
            "--sim-days", "14",
            "--seed", "42",
            "--output-dir", str(exp_dir)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            # 提取关键指标
            state_file = exp_dir / "state" / "agent_state_history.csv"
            if state_file.exists():
                df = pd.read_csv(state_file)
                metrics = {
                    "param_value": value,
                    "mean_emotion": df["emotion"].mean(),
                    "mean_stress": df["stress"].mean(),
                    "mean_econ_security": df["econ_security"].mean(),
                    "avg_travel_cost": df["daily_travel_cost"].mean() if "daily_travel_cost" in df.columns else None
                }
                results.append(metrics)

    # 计算敏感度：指标变化 / 参数变化
    sensitivity = {}
    if len(results) >= 2:
        param_change = results[-1]["param_value"] - results[0]["param_value"]
        for key in results[0]:
            if key != "param_value":
                metric_change = results[-1][key] - results[0][key]
                if param_change != 0:
                    sensitivity[key] = metric_change / param_change
                else:
                    sensitivity[key] = 0

    return {
        "param_name": param_name,
        "param_values": param_values,
        "results": results,
        "sensitivity": sensitivity
    }

def main():
    parser = argparse.ArgumentParser(description="敏感度分析")
    parser.add_argument("--param", help="参数名")
    parser.add_argument("--values", nargs="+", type=float, help="参数值列表")

    args = parser.parse_args()

    if args.param and args.values:
        results = run_sensitivity_analysis(args.param, args.values)
        print(json.dumps(results, indent=2, default=float))
    else:
        # 运行所有参数的敏感度分析
        all_results = {}
        for param, values in PARAM_RANGES.items():
            all_results[param] = run_sensitivity_analysis(param, values)

        print(json.dumps(all_results, indent=2, default=float))

        with open(EXPERIMENT_DIR / "sensitivity_results.json", "w") as f:
            json.dump(all_results, f, indent=2)

if __name__ == "__main__":
    main()
```

---

## 4. 验证报告格式

### 4.1 验证结果摘要表

```csv
metric,error_type,error_value,simulation_vs_reference
transport_mode_share,KL_divergence,0.085,"bus: sim=0.28 vs ref=0.25; metro: sim=0.32 vs ref=0.35"
engels_coefficient,relative_error,0.12,"sim=0.40 vs ref=0.35"
emotion_distribution,wasserstein_distance,0.08,"sim_mean=0.58 vs ref=0.60"
```

### 4.2 误差分析详情

```markdown
## 交通方式结构验证

### 仿真 vs 参考对比
| 方式 | 仿真比例 | 参考比例 | 绝对差异 | 相对差异 |
|------|----------|----------|----------|----------|
| 公交 | 0.28 | 0.25 | +0.03 | +12% |
| 地铁 | 0.32 | 0.35 | -0.03 | -9% |
| 出租 | 0.12 | 0.10 | +0.02 | +20% |
| 自驾 | 0.18 | 0.20 | -0.02 | -10% |
| 步行/骑行 | 0.10 | 0.10 | 0.00 | 0% |

### KL 散度：0.085
（0 = 完全一致，1 = 完全不同）

### 结论
模型较好地捕捉了出行方式结构，但出租车使用偏高（+20%），
可能需要调整出租车成本参数或增加公交吸引力。
```

---

## 5. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 收集参考基准数据 | 3天 |
| Phase 2 | 运行基础仿真 | 1天 |
| Phase 3 | 敏感度分析 | 3天 |
| Phase 4 | 误差量化与报告 | 2天 |
| **总计** | | **9天** |

---

## 6. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| ABM验证 | Axelrod (1997) *Advancing the Art of Simulation* | 提供可操作的验证框架 |
| 计算社会科学方法论 | Salganik (2018) *Bit by Bit* | 混合方法研究设计 |
| 模型校准 | Thiele et al. (2014) *EM-fitting* | 参数自动校准工具 |

---

## 7. 扩展方向

### 7.1 跨城市对比

将 GAWorld 与其他城市（上海、北京、深圳）的真实数据对比

### 7.2 时间序列验证

不仅验证静态分布，还验证动态变化趋势

### 7.3 极端情况测试

专门测试模型在极端情况（金融危机、自然灾害）下的表现