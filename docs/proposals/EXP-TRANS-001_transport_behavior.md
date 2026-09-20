# 实验提案：城市出行行为与交通政策评估

**提案编号**：EXP-TRANS-001
**研究领域**：城市科学 / 交通研究 / 政策模拟
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

- 城市居民如何选择出行方式（公交/地铁/出租/步行/自驾）？
- 天气、时间和收入如何共同影响出行决策？
- 交通政策（如高峰限行、地铁涨价）如何影响居民出行和行为？

### 1.2 研究假设

- **H1**：雨天时露天出行方式（步行/自行车）比例显著下降，有遮蔽方式上升
- **H2**：高峰时段（7-9点、17-19点）出租车选择率下降，公交/地铁比例上升
- **H3**：收入越高，选择私家车/出租车的概率越高
- **H4**：交通限行政策能改变出行方式结构，减少拥堵

### 1.3 关键指标

| 指标 | 说明 | 测量方式 |
|------|------|---------|
| `transport_mode` | 选择的交通方式 | 经济模块输出 |
| `daily_travel_cost` | 当日累计出行成本 | 经济模块追踪 |
| `commute_time` | 通勤时间 | 位置系统计算 |
| `location` | 当前地点 | 状态追踪 |

---

## 2. GAWorld 位置与交通系统能力

GAWorld 的 `city_map_system.py` 和 `economy_module.py` 提供了完整的出行仿真：

| 能力 | 说明 |
|------|------|
| 多种交通方式费率 | 公交2元/地铁0.45元/km/出租车13+2.5元/km |
| 高峰时段附加 | 7-9点/17-19点：出行时间×1.45，出租车附加×1.3 |
| 天气感知模式选择 | 雨天惩罚露天方式，自动切换到公交/地铁 |
| 出行成本计算 | 从经济模块扣除真实的交通费用 |
| 通勤记忆 | 追踪常去地点、偏好方式、路线统计 |

---

## 3. 实验设计

### 3.1 实验类型

**对照实验**（Policy comparison）+ **观察性研究**（Behavioral patterns）

### 3.2 实验组设计

| 实验组 | 说明 | 政策变量 |
|--------|------|---------|
| Control | 正常出行，无干预 | 无 |
| Treatment-weather | 注入不同天气事件 | 雨天/晴天/高温 |
| Treatment-rush | 高峰时段强化 | 7-9点出行成本×1.5 |
| Treatment-transit-price | 地铁涨价 | 地铁票价×1.5 |
| Treatment-car-restriction | 私家车限行 | 高峰期禁止自驾 |

### 3.3 天气注入方案

```python
WEATHER_EVENTS = {
    "rainy_day": {
        "name": "暴雨天气",
        "weather_type": "rain",
        "start_day": 3,
        "end_day": 5,
        "affected_hours": [7, 8, 9, 17, 18, 19],
        "description": "连续3天暴雨，早晚高峰受影响"
    },
    "hot_summer": {
        "name": "高温天气",
        "weather_type": "hot",
        "start_day": 7,
        "end_day": 10,
        "affected_hours": [10, 11, 12, 13, 14, 15],
        "description": "连续4天高温，露天出行意愿降低"
    }
}
```

---

## 4. 实施代码

### 4.1 实验脚本：`experiments/transport_behavior_exp.py`

```python
#!/usr/bin/env python3
"""
GAWorld 出行行为实验

运行方式：
    python experiments/transport_behavior_exp.py run --treatment treatment_weather --days 14 --seed 42

预期输出：
    output/experiments/transport/<treatment>/transport_decisions.csv
    output/experiments/transport/<treatment>/travel_cost_summary.csv
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

EXPERIMENT_DIR = Path("output/experiments/transport")

TREATMENTS = {
    "control": {
        "weather": None,
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "正常出行"
    },
    "treatment_weather_rain": {
        "weather": {
            "type": "rain",
            "start_day": 3,
            "end_day": 5,
            "hours": [7, 8, 9, 17, 18, 19]
        },
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "暴雨天气事件"
    },
    "treatment_weather_hot": {
        "weather": {
            "type": "hot",
            "start_day": 7,
            "end_day": 10,
            "hours": [10, 11, 12, 13, 14, 15]
        },
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "高温天气事件"
    },
    "treatment_transit_price": {
        "weather": None,
        "transit_price_multiplier": 1.5,  # 地铁涨价50%
        "car_restriction": False,
        "rush_hour_multiplier": 1.0,
        "description": "地铁涨价50%"
    },
    "treatment_car_restriction": {
        "weather": None,
        "transit_price_multiplier": 1.0,
        "car_restriction": True,  # 高峰期禁止自驾
        "rush_hour_multiplier": 1.0,
        "description": "私家车高峰限行"
    },
    "treatment_rush_hour_cost": {
        "weather": None,
        "transit_price_multiplier": 1.0,
        "car_restriction": False,
        "rush_hour_multiplier": 1.5,  # 高峰出行成本增加50%
        "description": "高峰时段出行成本上升"
    }
}

def setup_environment(treatment: str):
    """设置环境变量控制实验参数"""
    config = TREATMENTS[treatment]

    # 天气设置
    weather = config.get("weather")
    if weather:
        os.environ["GAWORLD_WEATHER_TYPE"] = weather["type"]
        os.environ["GAWORLD_WEATHER_START_DAY"] = str(weather["start_day"])
        os.environ["GAWORLD_WEATHER_END_DAY"] = str(weather["end_day"])
        os.environ["GAWORLD_WEATHER_HOURS"] = ",".join(map(str, weather["hours"]))

    # 交通价格
    os.environ["GAWORLD_TRANSIT_PRICE_MULT"] = str(config["transit_price_multiplier"])

    # 私家车限行
    os.environ["GAWORLD_CAR_RESTRICTION"] = str(config["car_restriction"]).lower()

    # 高峰成本
    os.environ["GAWORLD_RUSH_HOUR_MULT"] = str(config["rush_hour_multiplier"])

def run_treatment(treatment: str, days: int, seed: int):
    """运行单个实验组"""
    config = TREATMENTS[treatment]
    exp_dir = EXPERIMENT_DIR / treatment
    exp_dir.mkdir(parents=True, exist_ok=True)

    # 设置环境
    import os
    setup_environment(treatment)

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

def extract_transport_decisions(exp_dir: Path) -> pd.DataFrame:
    """提取交通决策数据"""
    # 从状态历史中提取出行相关信息
    state_file = exp_dir / "state" / "agent_state_history.csv"
    if not state_file.exists():
        return None

    df = pd.read_csv(state_file)

    # 提取每日出行信息
    transport_data = df[["day", "time", "agent_id", "location", "activity"]].copy()

    # 标记高峰时段
    def is_rush_hour(time_str):
        hour = int(time_str.split(":")[0])
        return hour in [7, 8, 9, 17, 18, 19]

    transport_data["is_rush_hour"] = transport_data["time"].apply(is_rush_hour)

    return transport_data

def compute_travel_metrics(exp_dir: Path) -> dict:
    """计算出行指标"""
    state_file = exp_dir / "state" / "agent_state_history.csv"
    if not state_file.exists():
        return {"error": "State file not found"}

    df = pd.read_csv(state_file)

    # 计算每日出行成本
    daily_travel = df.groupby("day").agg({
        "daily_travel_cost": ["mean", "std", "sum"] if "daily_travel_cost" in df.columns else None
    }).reset_index()

    # 统计各交通方式使用情况（从活动描述中推断）
    # 这里需要根据实际的数据格式来调整
    activity_mode_mapping = {
        "乘坐公交": "bus",
        "地铁": "metro",
        "出租车": "taxi",
        "步行": "walk",
        "自驾": "car",
        "骑自行车": "bike"
    }

    results = {
        "treatment": exp_dir.name,
        "avg_daily_travel_cost": df["daily_travel_cost"].mean() if "daily_travel_cost" in df.columns else None,
        "transport_mode_counts": {},  # 需要从活动数据中提取
        "rush_hour_travel_cost": None  # 需要专门计算
    }

    return results

def analyze_weather_impact():
    """分析天气对出行行为的影响"""
    rainy_dir = EXPERIMENT_DIR / "treatment_weather_rain"
    control_dir = EXPERIMENT_DIR / "control"

    if not rainy_dir.exists() or not control_dir.exists():
        print("[WARN] Missing experimental data")
        return

    rainy_df = pd.read_csv(rainy_dir / "state" / "agent_state_history.csv")
    control_df = pd.read_csv(control_dir / "state" / "agent_state_history.csv")

    # 对比雨天期间和非雨天期间的出行成本
    rainy_df["is_rainy_period"] = (rainy_df["day"] >= 3) & (rainy_df["day"] <= 5)

    results = {
        "rainy_period_travel_cost": rainy_df[rainy_df["is_rainy_period"]]["daily_travel_cost"].mean() if "daily_travel_cost" in rainy_df.columns else None,
        "non_rainy_period_travel_cost": rainy_df[~rainy_df["is_rainy_period"]]["daily_travel_cost"].mean() if "daily_travel_cost" in rainy_df.columns else None,
        "control_period_travel_cost": control_df["daily_travel_cost"].mean() if "daily_travel_cost" in control_df.columns else None
    }

    import json
    print(json.dumps(results, indent=2))

    return results

def compare_all_treatments():
    """对比所有实验组"""
    results = {}
    for treatment in TREATMENTS.keys():
        exp_dir = EXPERIMENT_DIR / treatment
        if exp_dir.exists():
            results[treatment] = compute_travel_metrics(exp_dir)

    import json
    print(json.dumps(results, indent=2, ensure_ascii=False))

    with open(EXPERIMENT_DIR / "comparison_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return results

def plot_transport_trends():
    """绘制交通行为趋势图"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not installed, skipping plot")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    treatments_to_plot = ["control", "treatment_weather_rain", "treatment_transit_price", "treatment_car_restriction"]

    for idx, treatment in enumerate(treatments_to_plot):
        ax = axes[idx // 2, idx % 2]
        exp_dir = EXPERIMENT_DIR / treatment

        state_file = exp_dir / "state" / "agent_state_history.csv"
        if not state_file.exists():
            continue

        df = pd.read_csv(state_file)

        # 绘制每日出行成本
        if "daily_travel_cost" in df.columns:
            daily_cost = df.groupby("day")["daily_travel_cost"].mean()
            ax.plot(daily_cost.index, daily_cost.values, marker='o')

        ax.set_title(treatment)
        ax.set_xlabel("Day")
        ax.set_ylabel("Avg Daily Travel Cost")
        ax.grid(True)

        # 标记政策变化时间点
        if treatment == "treatment_weather_rain":
            ax.axvspan(3, 5, alpha=0.3, color='blue', label='Rainy')
            ax.legend()

    plt.tight_layout()
    plt.savefig(EXPERIMENT_DIR / "transport_trends.png", dpi=150)
    print(f"[EXP] Saved plot to {EXPERIMENT_DIR / 'transport_trends.png'}")

def main():
    parser = argparse.ArgumentParser(description="出行行为实验")
    parser.add_argument("action", choices=["run", "analyze", "compare", "plot", "weather-impact"])
    parser.add_argument("--treatment", default="control",
                        help=f"实验组: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="仿真天数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()

    if args.action == "run":
        import os
        run_treatment(args.treatment, args.days, args.seed)
    elif args.action == "analyze":
        exp_dir = EXPERIMENT_DIR / args.treatment
        metrics = compute_travel_metrics(exp_dir)
        import json
        print(json.dumps(metrics, indent=2))
    elif args.action == "compare":
        compare_all_treatments()
    elif args.action == "plot":
        plot_transport_trends()
    elif args.action == "weather-impact":
        analyze_weather_impact()

if __name__ == "__main__":
    import os
    main()
```

### 4.2 出行选择模型分析：`experiments/transport_choice_model.py`

```python
#!/usr/bin/env python3
"""
出行方式选择模型分析

使用 Logit 模型分析影响出行选择的因素
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json

class TransportChoiceModel:
    def __init__(self, exp_dir: Path):
        self.exp_dir = exp_dir
        self.data = None

    def load_data(self):
        """加载出行数据"""
        state_file = self.exp_dir / "state" / "agent_state_history.csv"
        if not state_file.exists():
            return None

        self.data = pd.read_csv(state_file)
        return self.data

    def prepare_features(self) -> pd.DataFrame:
        """
        准备特征变量

        特征：时间（hour）、是否高峰、天气（需从环境配置获取）、
              收入水平（从经济数据获取）、智能体特征
        """
        if self.data is None:
            return None

        df = self.data.copy()

        # 提取小时
        df["hour"] = df["time"].apply(lambda x: int(x.split(":")[0]))

        # 高峰时段标志
        df["is_rush"] = df["hour"].isin([7, 8, 9, 17, 18, 19])

        # 工作日/周末（假设周末 = day % 7 in [0, 6] 对应周六日）
        df["is_weekend"] = df["day"] % 7 >= 5

        # 收入分层（需要从经济数据获取，这里简化处理）
        # 使用 agent_id 的某种映射来模拟收入
        df["income_level"] = df["agent_id"] % 3  # 0=低收入, 1=中收入, 2=高收入

        return df

    def estimate_mode_choice_model(self, df: pd.DataFrame) -> dict:
        """
        估计出行方式选择模型

        因变量：transport_mode（从 activity 中推断）
        自变量：hour, is_rush, is_weekend, income_level, emotion, stress

        这里使用简化的多项 Logit 近似
        """
        # 从活动描述中提取交通方式
        mode_map = {
            "公交": "bus",
            "地铁": "metro",
            "出租": "taxi",
            "步行": "walk",
            "自驾": "car",
            "自行车": "bike"
        }

        df["transport_mode"] = df["activity"].map(mode_map)
        df = df.dropna(subset=["transport_mode"])

        if len(df) < 50:
            return {"error": "Insufficient data"}

        # 简单统计：各因素对出行方式的影响
        results = {
            "mode_distribution": df["transport_mode"].value_counts().to_dict(),
            "mode_by_rush": df.groupby("is_rush")["transport_mode"].value_counts().unstack().fillna(0).to_dict(),
            "mode_by_income": df.groupby("income_level")["transport_mode"].value_counts().unstack().fillna(0).to_dict()
        }

        return results

    def compute_elasticities(self, df: pd.DataFrame) -> dict:
        """计算各因素的弹性（出行方式选择对因素的敏感度）"""

        # 简化弹性计算：各收入水平选择各方式的概率
        mode_by_income = df.groupby("income_level")["transport_mode"].value_counts(normalize=True).unstack()

        elasticities = {}
        for mode in mode_by_income.columns:
            mode_probs = mode_by_income[mode].values
            income_levels = mode_by_income.index.values

            # 简单计算：收入增加1个单位，方式选择概率的变化
            if len(mode_probs) >= 2:
                elasticity = (mode_probs[-1] - mode_probs[0]) / (income_levels[-1] - income_levels[0])
                elasticities[mode] = elasticity

        return elasticities

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python transport_choice_model.py <exp_dir>")
        sys.exit(1)

    exp_dir = Path(sys.argv[1])
    model = TransportChoiceModel(exp_dir)

    data = model.load_data()
    if data is None:
        print("[ERROR] No data found")
        sys.exit(1)

    df = model.prepare_features()
    results = model.estimate_mode_choice_model(df)
    elasticities = model.compute_elasticities(df)

    import json
    print("=== Mode Choice Analysis ===")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print("\n=== Elasticities ===")
    print(json.dumps(elasticities, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

---

## 5. 预期结果格式

### 5.1 出行决策数据

```csv
day,time,agent_id,location,activity,is_rush,daily_travel_cost,income_level
3,08:30,5,Central Station,地铁,True,8.5,2
3,08:30,12,Central Station,公交,True,2.0,1
3,08:30,23,Central Station,出租车,True,35.0,2
...
```

### 5.2 天气影响对比

```json
{
  "rainy_period_travel_cost": 28.5,
  "non_rainy_period_travel_cost": 22.3,
  "control_period_travel_cost": 23.1,
  "rain_premium": 5.2,
  "rain_premium_pct": 22.8
}
```

### 5.3 交通政策效果评估

```json
{
  "treatment_transit_price": {
    "avg_travel_cost_change": -12.5,
    "mode_shift": {
      "bus_increase_pct": 35,
      "metro_decrease_pct": 40,
      "taxi_increase_pct": 15
    }
  },
  "treatment_car_restriction": {
    "avg_travel_cost_change": 8.3,
    "mode_shift": {
      "bus_increase_pct": 25,
      "metro_increase_pct": 45,
      "taxi_increase_pct": 30
    }
  }
}
```

---

## 6. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 脚本开发 | 1天 |
| Phase 2 | 运行全部5组实验（各14天） | 2天 |
| Phase 3 | 出行选择模型估计 | 1天 |
| Phase 4 | 可视化与报告 | 1天 |
| **总计** | | **5天** |

---

## 7. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| 出行行为模型 | McFadden (1974) Conditional Logit | 提供可验证的出行选择模型 |
| 天气对出行影响 | Khattak et al. (2011) | 量化恶劣天气的出行选择改变 |
| 交通政策评估 | Litman (2004) Transportation Elasticities | 评估具体政策的量化效果 |

---

## 8. 扩展方向

### 8.1 通勤满意度研究

结合情绪和压力数据，分析通勤时间与主观幸福感的关系

### 8.2 长期通勤影响

识别高通勤时间智能体，观察长期累积效应

### 8.3 多政策组合

测试"地铁涨价+高峰限行"组合效果 vs 单项政策效果