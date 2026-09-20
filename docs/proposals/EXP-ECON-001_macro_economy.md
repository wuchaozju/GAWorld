# 实验提案：宏观经济周期与居民福祉

**提案编号**：EXP-ECON-001
**研究领域**：经济学 / 计算社会科学
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

宏观经济周期（扩张/峰值/收缩/谷底）如何影响居民的情绪、压力和经济安全感？

### 1.2 研究假设

- **H1**：宏观周期对不同收入水平智能体的影响是非对称的
- **H2**：经济下行期低收入智能体的 `econ_security` 下降幅度大于高收入者
- **H3**：宏观冲击后智能体需要 30-90 天恢复（与经济模块的 shock 参数一致）
- **H4**：职业类型（行业）影响冲击敏感度

### 1.3 关键指标

| 指标 | 说明 | 测量方式 |
|------|------|---------|
| `emotion` | 情绪状态 | CSV 初始 + 实时追踪 |
| `stress` | 压力水平 | CSV 初始 + 实时追踪 |
| `econ_security` | 经济安全感 | CSV 初始 + 实时追踪 |
| `income` | 实际收入 | 经济模块输出 |
| `savings_rate` | 储蓄率 | 经济模块计算 |
| `unemployment` | 失业状态 | 经济模块冲击事件 |

---

## 2. GAWorld 经济模块能力

GAWorld 的 `economy_module.py` 已实现完整的宏观经济仿真：

| 子系统 | 说明 |
|--------|------|
| 四阶段宏观周期 | 扩张(60-180天)→峰值→收缩→谷底，循环往复 |
| 行业景气度 | 科技/金融/医疗/教育/服务/贸易独立波动 |
| 每日通胀 | 按日累积，侵蚀购买力 |
| 冲击事件 | 裁员(-50~85%收入)、涨薪、大病、年终奖 |
| 消费结构 | 八大消费类目，恩格尔系数模型 |

---

## 3. 实验设计

### 3.1 实验类型

**纵向追踪实验**（Longitudinal tracking）：运行 60+ 天以捕获至少一个完整宏观周期

### 3.2 实验组设计

| 实验组 | 说明 | 样本量 |
|--------|------|--------|
| All-agents | 所有50个智能体，完整宏观周期 | 50 |
| High-income | 收入前25%的智能体 | ~12 |
| Low-income | 收入后25%的智能体 | ~12 |
| Tech-industry | 科技行业从业者 | ~8 |
| Service-industry | 服务业从业者 | ~8 |

### 3.3 测量频率

- 每个模拟天（day）记录一次完整状态
- 每个模拟天记录经济状态（收入、支出、储蓄）
- 宏观周期切换时记录快照

### 3.4 时间轴设计

```
Day 1-30:   宏观扩张期（Expansion）
Day 31-60:  宏观峰值（Peak）
Day 61-90:  宏观收缩（Contraction）
Day 91-120: 宏观谷底（Trough）
Day 121-150: 新一轮扩张（完成完整周期）
```

---

## 4. 实施代码

### 4.1 实验脚本：`experiments/macro_economy_exp.py`

```python
#!/usr/bin/env python3
"""
GAWorld 宏观经济周期实验

运行方式：
    python experiments/macro_economy_exp.py run --days 150 --seed 42

预期输出：
    output/experiments/macro_economy/macro_metrics.csv
    output/experiments/macro_economy/agent_wellbeing.csv
    output/experiments/macro_economy/macro_state.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

EXPERIMENT_DIR = Path("output/experiments/macro_economy")

def run_simulation(days: int, seed: int):
    """运行长期仿真"""
    exp_dir = EXPERIMENT_DIR / f"run_{seed}"
    exp_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "experiment": "macro_economy_wellbeing",
        "days": days,
        "seed": seed,
        "timestamp": datetime.now().isoformat()
    }
    with open(exp_dir / "experiment_config.json", "w") as f:
        json.dump(config, f, indent=2)

    cmd = [
        "python", "generative_city_sim.py", "run",
        "--sim-days", str(days),
        "--seed", str(seed),
        "--output-dir", str(exp_dir)
    ]

    print(f"[EXP] Running macro economy simulation: days={days} seed={seed}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}", file=sys.stderr)
        return False

    return True

def analyze_results(seed: int):
    """分析宏观周期对居民福祉的影响"""
    exp_dir = EXPERIMENT_DIR / f"run_{seed}"

    # 读取经济数据
    economy_dir = exp_dir / "economy"
    if not economy_dir.exists():
        print(f"[ERROR] Economy directory not found: {economy_dir}")
        return None

    # 读取宏观状态
    macro_state_file = economy_dir / "macro_state.json"
    if macro_state_file.exists():
        with open(macro_state_file) as f:
            macro_state = json.load(f)

    # 读取每日账本
    ledger_file = economy_dir / "daily_ledger.csv"
    if not ledger_file.exists():
        print(f"[ERROR] Ledger file not found: {ledger_file}")
        return None

    import pandas as pd
    ledger_df = pd.read_csv(ledger_file)

    # 读取智能体状态历史
    state_file = exp_dir / "state" / "agent_state_history.csv"
    state_df = pd.read_csv(state_file)

    # 合并数据
    merged_df = pd.merge(state_df, ledger_df, on=["day", "agent_id"])

    # 计算福祉指标
    results = {}

    # 按宏观阶段聚合
    # 需要从 macro_state 获取阶段切换时间
    # 这里假设每30天为一个阶段
    merged_df["macro_phase"] = (merged_df["day"] - 1) // 30 + 1

    phase_metrics = merged_df.groupby("macro_phase").agg({
        "emotion": ["mean", "std"],
        "stress": ["mean", "std"],
        "econ_security": ["mean", "std"],
        "income": "mean",
        "savings_rate": "mean" if "savings_rate" in merged_df.columns else None
    }).reset_index()

    results["phase_metrics"] = phase_metrics.to_dict()

    # 收入分层分析
    income_groups = pd.qcut(merged_df.groupby("agent_id")["income"].mean(), q=4, labels=["Q1", "Q2", "Q3", "Q4"])
    merged_df["income_quartile"] = merged_df["agent_id"].map(income_groups)

    quartile_by_phase = merged_df.groupby(["macro_phase", "income_quartile"]).agg({
        "econ_security": "mean",
        "stress": "mean",
        "emotion": "mean"
    }).reset_index()

    results["quartile_by_phase"] = quartile_by_phase.to_dict()

    # 保存结果
    with open(exp_dir / "wellbeing_analysis.json", "w") as f:
        json.dump(results, f, indent=2)

    return results

def generate_report(seed: int):
    """生成分析报告"""
    exp_dir = EXPERIMENT_DIR / f"run_{seed}"

    import pandas as pd

    # 读取数据
    ledger_df = pd.read_csv(exp_dir / "economy" / "daily_ledger.csv")
    state_df = pd.read_csv(exp_dir / "state" / "agent_state_history.csv")

    # 生成报告
    report_lines = []
    report_lines.append("# 宏观经济周期与居民福祉分析报告\n")
    report_lines.append(f"实验配置：{days}天仿真，seed={seed}\n")

    # 宏观阶段影响
    report_lines.append("## 宏观阶段对居民福祉的影响\n")
    report_lines.append("| 阶段 | 平均情绪 | 平均压力 | 平均经济安全 |\n")
    report_lines.append("|------|---------|---------|------------|\n")

    for phase in range(1, 6):  # 假设最多5个阶段
        phase_data = state_df[(state_df["day"] >= (phase-1)*30 + 1) & (state_df["day"] <= phase*30)]
        if len(phase_data) > 0:
            report_lines.append(f"| {phase} | {phase_data['emotion'].mean():.3f} "
                             f"| {phase_data['stress'].mean():.3f} "
                             f"| {phase_data['econ_security'].mean():.3f} |\n")

    report_text = "".join(report_lines)
    print(report_text)

    # 保存报告
    with open(exp_dir / "wellbeing_report.md", "w") as f:
        f.write(report_text)

def main():
    parser = argparse.ArgumentParser(description="宏观经济周期实验")
    parser.add_argument("action", choices=["run", "analyze", "report"])
    parser.add_argument("--days", type=int, default=150, help="仿真天数（建议>=120以捕获完整周期）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    global days
    args = parser.parse_args()
    days = args.days

    if args.action == "run":
        run_simulation(args.days, args.seed)
    elif args.action == "analyze":
        results = analyze_results(args.seed)
        if results:
            import json
            print(json.dumps(results, indent=2))
    elif args.action == "report":
        generate_report(args.seed)

if __name__ == "__main__":
    main()
```

### 4.2 宏观周期可视化：`experiments/visualize_macro.py`

```python
#!/usr/bin/env python3
"""
宏观经济周期与福祉可视化

生成图表展示宏观周期对居民的影响
"""

import json
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

def plot_macro_wellbeing(exp_dir: Path, output_dir: Path):
    """绘制宏观周期与福祉关系图"""
    try:
        import matplotlib
        matplotlib.use('Agg')  # 无头模式
        plt.style.use('seaborn-v0_8-whitegrid')
    except ImportError:
        print("[WARN] matplotlib not installed, skipping plot")
        return

    # 读取数据
    state_df = pd.read_csv(exp_dir / "state" / "agent_state_history.csv")
    ledger_df = pd.read_csv(exp_dir / "economy" / "daily_ledger.csv")
    macro_state_file = exp_dir / "economy" / "macro_state.json"

    with open(macro_state_file) as f:
        macro_state = json.load(f)

    # 创建图表
    fig, axes = plt.subplots(3, 2, figsize=(14, 12))

    # 1. 情绪趋势
    daily_emotion = state_df.groupby("day")["emotion"].mean()
    daily_stress = state_df.groupby("day")["stress"].mean()
    daily_econ_sec = state_df.groupby("day")["econ_security"].mean()

    ax1 = axes[0, 0]
    ax1.plot(daily_emotion.index, daily_emotion.values, label='Emotion', color='green')
    ax1.fill_between(daily_emotion.index, daily_emotion.values, alpha=0.3)
    ax1.set_title("Average Emotion Over Time")
    ax1.set_xlabel("Day")
    ax1.set_ylabel("Emotion (0-1)")
    ax1.legend()

    # 2. 压力趋势
    ax2 = axes[0, 1]
    ax2.plot(daily_stress.index, daily_stress.values, label='Stress', color='red')
    ax2.fill_between(daily_stress.index, daily_stress.values, alpha=0.3, color='red')
    ax2.set_title("Average Stress Over Time")
    ax2.set_xlabel("Day")
    ax2.set_ylabel("Stress (0-1)")
    ax2.legend()

    # 3. 经济安全感趋势
    ax3 = axes[1, 0]
    ax3.plot(daily_econ_sec.index, daily_econ_sec.values, label='Econ Security', color='blue')
    ax3.fill_between(daily_econ_sec.index, daily_econ_sec.values, alpha=0.3, color='blue')
    ax3.set_title("Average Economic Security Over Time")
    ax3.set_xlabel("Day")
    ax3.set_ylabel("Econ Security (0-1)")
    ax3.legend()

    # 4. 宏观阶段标注
    ax4 = axes[1, 1]
    phases = macro_state.get("phase_sequence", [])
    phase_colors = {"expansion": "green", "peak": "yellow", "contraction": "orange", "trough": "red"}

    for i, phase in enumerate(phases):
        start_day = i * 30 + 1
        end_day = min((i + 1) * 30, state_df["day"].max())
        color = phase_colors.get(phase, "gray")
        ax4.axvspan(start_day, end_day, alpha=0.3, color=color, label=phase)
        ax4.text((start_day + end_day) / 2, 0.5, phase.upper(), ha='center', fontsize=8)

    ax4.set_title("Macro Economic Phase")
    ax4.set_xlabel("Day")
    ax4.set_ylim(0, 1)
    ax4.legend(loc='upper right')
    ax4.set_xlim(1, state_df["day"].max())

    # 5. 收入与福祉关系（按收入四分位）
    ax5 = axes[2, 0]
    state_df["income_quartile"] = pd.qcut(state_df.groupby("agent_id")["income"].transform("mean"),
                                          q=4, labels=["Q1(Low)", "Q2", "Q3", "Q4(High)"], duplicates='drop')
    for quartile in ["Q1(Low)", "Q2", "Q3", "Q4(High)"]:
        subset = state_df[state_df["income_quartile"] == quartile]
        daily_mean = subset.groupby("day")["econ_security"].mean()
        ax5.plot(daily_mean.index, daily_mean.values, label=quartile)

    ax5.set_title("Economic Security by Income Quartile")
    ax5.set_xlabel("Day")
    ax5.set_ylabel("Econ Security")
    ax5.legend()

    # 6. 宏观周期与情绪热力图
    ax6 = axes[2, 1]
    state_df["macro_phase"] = (state_df["day"] - 1) // 30 + 1
    pivot = state_df.pivot_table(values="emotion", index="macro_phase", columns="income_quartile", aggfunc="mean")
    im = ax6.imshow(pivot.values, cmap='RdYlGn', aspect='auto')
    ax6.set_xticks(range(len(pivot.columns)))
    ax6.set_xticklabels(pivot.columns, rotation=45)
    ax6.set_yticks(range(len(pivot.index)))
    ax6.set_yticklabels([f"Phase {i}" for i in pivot.index])
    ax6.set_title("Emotion Heatmap: Macro Phase x Income")
    plt.colorbar(im, ax=ax6)

    plt.tight_layout()
    output_path = output_dir / "macro_wellbeing.png"
    plt.savefig(output_path, dpi=150)
    print(f"[EXP] Saved plot to {output_path}")

def main():
    import sys
    if len(sys.argv) < 3:
        print("Usage: python visualize_macro.py <exp_dir> <output_dir>")
        sys.exit(1)

    exp_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    plot_macro_wellbeing(exp_dir, output_dir)

if __name__ == "__main__":
    main()
```

---

## 5. 测量指标详解

### 5.1 核心福祉指标

| 指标 | 日变化计算 | 宏观周期关联分析 |
|------|-----------|----------------|
| emotion | 日均值 ± 标准差 | 每阶段均值对比 |
| stress | 日均值 | 压力峰值对应的宏观阶段 |
| econ_security | 日均值 | 经济安全感下降幅度/恢复时间 |

### 5.2 经济状态指标

| 指标 | 数据来源 |
|------|---------|
| gross_income | `agent_<id>_ledger.csv` |
| tax | `agent_<id>_ledger.csv` |
| net_income | 计算得出 |
| consumption_by_category | `daily_ledger.csv` |
| savings_rate | 储蓄/消费 |
| investment_returns | `macro_state.json` |

---

## 6. 预期结果格式

### 6.1 宏观阶段福祉表

```csv
macro_phase,avg_emotion,avg_stress,avg_econ_security,avg_income,avg_savings_rate
1 (Expansion),0.62,0.38,0.65,15000,0.22
2 (Peak),0.60,0.42,0.68,15800,0.25
3 (Contraction),0.52,0.55,0.52,14200,0.15
4 (Trough),0.45,0.62,0.38,12500,0.08
5 (Expansion),0.58,0.45,0.55,13500,0.18
```

### 6.2 收入分层×宏观阶段矩阵

```csv
macro_phase,income_quartile,avg_econ_security,avg_stress,avg_emotion
1,Q1(Low),0.45,0.52,0.48
1,Q2,0.58,0.45,0.55
1,Q3,0.68,0.38,0.62
1,Q4(High),0.78,0.28,0.70
3,Q1(Low),0.28,0.72,0.35  # 收缩期低收入受冲击更大
3,Q4(High),0.58,0.45,0.52
```

---

## 7. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 脚本开发 | 1天 |
| Phase 2 | 运行150天仿真 | 1天（假设每次仿真约30分钟）|
| Phase 3 | 数据分析 | 1天 |
| Phase 4 | 可视化与报告 | 1天 |
| **总计** | | **4天** |

---

## 8. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| 经济周期与幸福感 | Clark et al. (2018) *Unhappy voters and the business cycle* | 提供微观机制解释 |
| 不平等放大效应 | Piketty (2014) *Capital in the Twenty-First Century* | 量化宏观周期对收入不平等的影响 |
| 社会保险缓冲作用 | Chetty et al. (2018) | 评估不同储蓄率智能体的抗冲击能力 |

---

## 9. 扩展方向

### 9.1 政策干预实验

在宏观下行期注入政策（如临时补贴、失业救助），测量对福祉的缓冲作用

### 9.2 职业对比深度分析

深入分析科技业 vs 服务业在相同宏观阶段的表现差异

### 9.3 恢复动态研究

专门测量经济冲击后智能体的恢复时间分布