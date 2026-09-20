# 实验提案：智能体行为一致性与记忆架构验证

**提案编号**：EXP-MEM-001
**研究领域**：人工智能 / 多智能体系统
**创建日期**：2026年5月14日
**状态**：待执行

---

## 1. 研究背景与目标

### 1.1 研究问题

- 具有长期记忆的 LLM 智能体是否在跨天决策中保持一致？
- 记忆系统（episodic vs long-term summary）如何影响行为一致性？
- 不同类型的记忆对行为一致性的贡献分别有多大？

### 1.2 研究假设

- **H1**：有完整记忆的智能体比无记忆（reset后）智能体表现出更高的行为一致性
- **H2**：记忆越丰富，智能体对相似情境的响应越一致
- **H3**：长期总结（summary）比 episodic memory 对行为一致性的贡献更大
- **H4**：冲突记忆会导致决策摇摆，增加行为方差

### 1.3 关键指标

| 指标 | 说明 | 测量方式 |
|------|------|---------|
| 行为一致性 | 相似情境下行动选择的相似度 | 每日计算 |
| 记忆召回率 | 感知阶段召回的相关记忆比例 | 日志分析 |
| 决策稳定性 | 同一问题多次回答的一致性 | 采访问答 |
| 记忆整合度 | 新记忆与旧记忆的融合程度 | 记忆文件分析 |

---

## 2. GAWorld 记忆系统能力

| 记忆类型 | 说明 | 存储位置 |
|---------|------|---------|
| Episodic Memory | 每个行为决策的背景和结果 | `agent_<id>_episodes.jsonl` |
| Long-term Summary | 智能体对自身的认知和目标总结 | `agent_<id>.json` |
| 关系记忆 | 与其他智能体的关系变化 | `agent_<id>.json` |
| 通勤记忆 | 常去地点、偏好方式 | 状态追踪 |
| 兴趣/技能成长 | `growth_profile` | `agent_<id>_growth.json` |

---

## 3. 实验设计

### 3.1 实验类型

**对比实验**（Memory vs No-memory）+ **纵向追踪**（Longitudinal tracking）

### 3.2 实验组设计

| 实验组 | 说明 | 设计目的 |
|--------|------|---------|
| Memory-intact | 完整记忆运行7天 | 基线：正常记忆累积 |
| Memory-reset | Day 1后 reset，Day 2-7重新运行 | 无记忆：测试记忆缺失影响 |
| Memory-selective | 仅保留 episodic，删除 summary | 测试不同记忆类型贡献 |
| Memory-conflict | Day 3 通过 RAG 注入冲突记忆 | 测试冲突记忆影响 |

### 3.3 一致性测量场景设计

为了让智能体面对"相似情境"，设计重复出现的场景：

```python
CONSISTENT_SCENARIOS = [
    {
        "name": "monday_morning_commute",
        "day_pattern": [1, 8, 15],  # 每周一
        "time": "08:00",
        "question": "今天要去上班，你的出行计划是什么？",
        "trigger": "问相同问题，观察回答一致性"
    },
    {
        "name": "friday_evening",
        "day_pattern": [5, 12, 19],  # 每周五
        "time": "18:00",
        "question": "周末有什么计划？",
        "trigger": "问相同问题，观察偏好一致性"
    }
]
```

---

## 4. 实施代码

### 4.1 实验脚本：`experiments/memory_consistency_exp.py`

```python
#!/usr/bin/env python3
"""
GAWorld 行为一致性实验

运行方式：
    python experiments/memory_consistency_exp.py run --treatment memory_intact --days 14 --seed 42

预期输出：
    output/experiments/memory_consistency/<treatment>/consistency_scores.csv
    output/experiments/memory_consistency/<treatment>/interview_responses.json
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

EXPERIMENT_DIR = Path("output/experiments/memory_consistency")

TREATMENTS = {
    "memory_intact": {
        "reset_between_phases": False,
        "delete_summaries": False,
        "inject_conflict": False,
        "description": "完整记忆运行"
    },
    "memory_reset": {
        "reset_between_phases": True,  # Day 1 后 reset
        "delete_summaries": False,
        "inject_conflict": False,
        "description": "无记忆运行（reset后重新开始）"
    },
    "memory_selective": {
        "reset_between_phases": False,
        "delete_summaries": True,  # 删除 long-term summary
        "inject_conflict": False,
        "description": "仅保留 episodic memory"
    },
    "memory_conflict": {
        "reset_between_phases": False,
        "delete_summaries": False,
        "inject_conflict": True,  # Day 3 注入冲突记忆
        "description": "注入冲突记忆"
    }
}

SCENARIO_QUESTIONS = [
    "今天要去上班，你的出行计划是什么？",
    "周末有什么安排？",
    "你最近压力大吗？有什么烦恼？",
    "你和朋友的关系如何？",
    "你对目前的收入满意吗？"
]

def run_phase(exp_dir: Path, phase: int, days: int, seed: int, config: dict) -> bool:
    """运行单个阶段"""
    phase_dir = exp_dir / f"phase_{phase}"
    phase_dir.mkdir(parents=True, exist_ok=True)

    # 应用实验处理
    if config.get("reset_between_phases") and phase == 2:
        # Phase 2 开始前 reset
        print(f"[EXP] Resetting for phase 2 in treatment {exp_dir.name}")
        subprocess.run(["python", "generative_city_sim.py", "reset"],
                      capture_output=True)

    if config.get("delete_summaries"):
        # 删除长期总结（保留 episodic）
        memory_dir = exp_dir / "memory"
        for mf in memory_dir.glob("agent_*_summary.json"):
            mf.unlink()

    if config.get("inject_conflict") and phase == 2:
        # Phase 2 Day 3 注入冲突记忆
        inject_conflict_memory(exp_dir)

    # 运行仿真
    cmd = [
        "python", "generative_city_sim.py", "run",
        "--sim-days", str(days),
        "--seed", str(seed + phase * 100),  # 不同 phase 用不同 seed
        "--output-dir", str(phase_dir)
    ]

    print(f"[EXP] Running phase {phase}: days={days} seed={seed + phase * 100}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def inject_conflict_memory(exp_dir: Path):
    """注入冲突记忆"""
    import random

    # 随机选择智能体注入冲突记忆
    conflict_agents = random.sample(range(1, 51), 5)

    for agent_id in conflict_agents:
        cmd = [
            "python", "generative_city_sim.py", "rag-add",
            "--agent-id", str(agent_id),
            "--text", "最近做了一个重大决定：辞掉工作去旅行一年，这个决定让我感到前所未有的自由和快乐",
            "--timestamp", "Day3 10:00",
            "--source", "experiment_conflict"
        ]
        subprocess.run(cmd, capture_output=True)

    print(f"[EXP] Injected conflict memories to agents: {conflict_agents}")

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
        "timestamp": datetime.now().isoformat(),
        "scenarios": SCENARIO_QUESTIONS
    }
    with open(exp_dir / "experiment_config.json", "w") as f:
        json.dump(config_record, f, indent=2, ensure_ascii=False)

    # 运行两个阶段
    # Phase 1: Day 1-7
    if not run_phase(exp_dir, 1, 7, seed, config):
        return False

    # 运行阶段间的采访问答
    run_interviews(exp_dir, phase=1)

    # Phase 2: Day 8-14 (或 reset 后重新运行)
    if config.get("reset_between_phases"):
        # 先 reset
        subprocess.run(["python", "generative_city_sim.py", "reset"],
                      capture_output=True)
        # 重新运行
        if not run_phase(exp_dir, 2, 7, seed, config):
            return False
    else:
        # 继续运行（不清除记忆）
        if not run_phase(exp_dir, 2, 7, seed, config):
            return False

    # Phase 2 采访问答
    run_interviews(exp_dir, phase=2)

    return True

def run_interviews(exp_dir: Path, phase: int):
    """在指定阶段运行采访问答"""
    interview_dir = exp_dir / f"phase_{phase}_interviews"
    interview_dir.mkdir(parents=True, exist_ok=True)

    # 选择代表性智能体
    sample_agents = [1, 10, 20, 30, 40, 50]

    responses = []
    for agent_id in sample_agents:
        for question in SCENARIO_QUESTIONS[:3]:  # 简化：只问前3个问题
            cmd = [
                "python", "generative_city_sim.py", "interview",
                "--agent-id", str(agent_id),
                "--question", question
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                responses.append({
                    "phase": phase,
                    "agent_id": agent_id,
                    "question": question,
                    "response": result.stdout
                })

    # 保存采访问答
    with open(interview_dir / "responses.json", "w") as f:
        json.dump(responses, f, indent=2, ensure_ascii=False)

def compute_consistency_score(exp_dir: Path, treatment: str) -> dict:
    """计算行为一致性分数"""
    results = {}

    for phase in [1, 2]:
        phase_dir = exp_dir / f"phase_{phase}"
        if not phase_dir.exists():
            continue

        # 读取采访问答
        interview_file = phase_dir / "interviews" / "responses.json"
        if interview_file.exists():
            with open(interview_file) as f:
                responses = json.load(f)

            # 计算同一智能体、同一问题的回答一致性
            agent_responses = {}
            for r in responses:
                key = f"{r['agent_id']}_{r['question']}"
                if key not in agent_responses:
                    agent_responses[key] = []
                agent_responses[key].append(r["response"])

            # 计算回答的相似度（简化：用回答长度方差）
            consistencies = {}
            for key, resps in agent_responses.items():
                if len(resps) > 1:
                    lengths = [len(r) for r in resps]
                    consistencies[key] = 1 - np.std(lengths) / np.mean(lengths) if np.mean(lengths) > 0 else 0

            results[f"phase_{phase}_consistency"] = {
                "mean_consistency": np.mean(list(consistencies.values())) if consistencies else None,
                "n_comparisons": len(consistencies)
            }

    # 计算跨阶段一致性
    phase1_dir = exp_dir / "phase_1"
    phase2_dir = exp_dir / "phase_2"

    if phase1_dir.exists() and phase2_dir.exists():
        # 比较同一智能体在相似情境下的回答
        cross_phase_consistency = compute_cross_phase_consistency(phase1_dir, phase2_dir)
        results["cross_phase_consistency"] = cross_phase_consistency

    return results

def compute_cross_phase_consistency(phase1_dir: Path, phase2_dir: Path) -> dict:
    """计算跨阶段一致性"""
    try:
        with open(phase1_dir / "interviews" / "responses.json") as f:
            phase1_responses = json.load(f)
        with open(phase2_dir / "interviews" / "responses.json") as f:
            phase2_responses = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"error": "Interview files not found"}

    # 按智能体和问题分组
    p1_by_key = {}
    for r in phase1_responses:
        key = f"{r['agent_id']}_{r['question']}"
        p1_by_key[key] = r["response"]

    p2_by_key = {}
    for r in phase2_responses:
        key = f"{r['agent_id']}_{r['question']}"
        p2_by_key[key] = r["response"]

    # 计算共同问题的回答相似度
    common_keys = set(p1_by_key.keys()) & set(p2_by_key.keys())
    similarities = []

    for key in common_keys:
        resp1 = p1_by_key[key]
        resp2 = p2_by_key[key]

        # 简化相似度：用共同词比例
        words1 = set(resp1.lower().split())
        words2 = set(resp2.lower().split())
        jaccard = len(words1 & words2) / len(words1 | words2) if words1 | words2 else 0
        similarities.append(jaccard)

    return {
        "n_common_questions": len(common_keys),
        "mean_similarity": np.mean(similarities) if similarities else None,
        "std_similarity": np.std(similarities) if similarities else None
    }

def analyze_memory_impact():
    """分析记忆对一致性的影响"""
    results = {}

    for treatment in TREATMENTS.keys():
        exp_dir = EXPERIMENT_DIR / treatment
        if exp_dir.exists():
            consistency = compute_consistency_score(exp_dir, treatment)
            results[treatment] = consistency

    import json
    print(json.dumps(results, indent=2, ensure_ascii=False))

    # 生成对比报告
    report_lines = ["# 记忆与行为一致性分析报告\n"]
    report_lines.append("| Treatment | Phase 1 Consistency | Phase 2 Consistency | Cross-Phase |")
    report_lines.append("|-----------|-------------------|-------------------|------------|")

    for treatment, data in results.items():
        p1 = data.get("phase_1_consistency", {}).get("mean_consistency", "N/A")
        p2 = data.get("phase_2_consistency", {}).get("mean_consistency", "N/A")
        cross = data.get("cross_phase_consistency", {}).get("mean_similarity", "N/A")
        report_lines.append(f"| {treatment} | {p1:.3f} | {p2:.3f} | {cross:.3f} |")

    report_text = "\n".join(report_lines)
    print("\n" + report_text)

    with open(EXPERIMENT_DIR / "consistency_report.md", "w") as f:
        f.write(report_text)

    return results

def plot_consistency_comparison():
    """绘制一致性对比图"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not installed, skipping plot")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    treatments = list(TREATMENTS.keys())
    p1_scores = []
    p2_scores = []

    for treatment in treatments:
        exp_dir = EXPERIMENT_DIR / treatment
        consistency = compute_consistency_score(exp_dir, treatment)

        p1 = consistency.get("phase_1_consistency", {}).get("mean_consistency", 0)
        p2 = consistency.get("phase_2_consistency", {}).get("mean_consistency", 0)

        p1_scores.append(p1 if p1 else 0)
        p2_scores.append(p2 if p2 else 0)

    x = np.arange(len(treatments))
    width = 0.35

    ax.bar(x - width/2, p1_scores, width, label='Phase 1')
    ax.bar(x + width/2, p2_scores, width, label='Phase 2')

    ax.set_xlabel('Treatment')
    ax.set_ylabel('Consistency Score')
    ax.set_title('Behavioral Consistency by Treatment')
    ax.set_xticks(x)
    ax.set_xticklabels(treatments, rotation=45, ha='right')
    ax.legend()
    ax.grid(True, axis='y')

    plt.tight_layout()
    plt.savefig(EXPERIMENT_DIR / "consistency_comparison.png", dpi=150)
    print(f"[EXP] Saved plot to {EXPERIMENT_DIR / 'consistency_comparison.png'}")

def main():
    parser = argparse.ArgumentParser(description="行为一致性实验")
    parser.add_argument("action", choices=["run", "analyze", "compare", "plot"])
    parser.add_argument("--treatment", default="memory_intact",
                        help=f"实验组: {', '.join(TREATMENTS.keys())}")
    parser.add_argument("--days", type=int, default=14, help="仿真天数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()

    if args.action == "run":
        run_treatment(args.treatment, args.days, args.seed)
    elif args.action == "analyze":
        exp_dir = EXPERIMENT_DIR / args.treatment
        consistency = compute_consistency_score(exp_dir, args.treatment)
        import json
        print(json.dumps(consistency, indent=2))
    elif args.action == "compare":
        analyze_memory_impact()
    elif args.action == "plot":
        plot_consistency_comparison()

if __name__ == "__main__":
    main()
```

### 4.2 记忆分析工具：`experiments/memory_analyzer.py`

```python
#!/usr/bin/env python3
"""
记忆分析工具

分析记忆文件，量化不同记忆类型的贡献
"""

import json
import pandas as pd
from pathlib import Path
from collections import Counter

class MemoryAnalyzer:
    def __init__(self, exp_dir: Path):
        self.exp_dir = exp_dir
        self.memory_files = {}

    def load_agent_memory(self, agent_id: int) -> dict:
        """加载单个智能体的记忆文件"""
        memory_dir = self.exp_dir / "memory"

        files = {
            "main": memory_dir / f"agent_{agent_id}.json",
            "episodes": memory_dir / f"agent_{agent_id}_episodes.jsonl",
            "growth": memory_dir / f"agent_{agent_id}_growth.json"
        }

        memory_data = {}

        if files["main"].exists():
            with open(files["main"]) as f:
                memory_data["main"] = json.load(f)

        if files["episodes"].exists():
            episodes = []
            with open(files["episodes"]) as f:
                for line in f:
                    episodes.append(json.loads(line))
            memory_data["episodes"] = episodes

        if files["growth"].exists():
            with open(files["growth"]) as f:
                memory_data["growth"] = json.load(f)

        self.memory_files[agent_id] = memory_data
        return memory_data

    def compute_memory_complexity(self, agent_id: int) -> dict:
        """计算记忆复杂度指标"""
        memory = self.memory_files.get(agent_id)
        if not memory:
            return {}

        metrics = {}

        # 主记忆复杂度
        if "main" in memory:
            main_mem = memory["main"]
            metrics["num_episodes"] = len(main_mem.get("episodes", []))
            metrics["num_relationships"] = len(main_mem.get("relationships", []))
            metrics["summary_length"] = len(main_mem.get("summary", "").split()) if main_mem.get("summary") else 0

        # Episodes 复杂度
        if "episodes" in memory:
            episodes = memory["episodes"]
            metrics["total_episodes"] = len(episodes)
            metrics["avg_episode_length"] = sum(len(e.get("content", "").split()) for e in episodes) / len(episodes) if episodes else 0

        # Growth 复杂度
        if "growth" in memory:
            growth = memory["growth"]
            metrics["num_interests"] = len(growth.get("interests", []))
            metrics["num_skills"] = len(growth.get("skills", []))
            metrics["total_practice_minutes"] = sum(i.get("total_minutes", 0) for i in growth.get("interests", []))

        return metrics

    def memory_retention_analysis(self, agent_id: int) -> dict:
        """分析记忆保留情况"""
        memory = self.memory_files.get(agent_id)
        if not memory or "episodes" not in memory:
            return {}

        episodes = memory["episodes"]

        # 按时间分布
        day_counts = Counter()
        for ep in episodes:
            day = ep.get("day", 0)
            day_counts[day] += 1

        # 计算记忆密度（每天多少 episodes）
        if day_counts:
            avg_daily = len(episodes) / len(day_counts)
        else:
            avg_daily = 0

        return {
            "total_episodes": len(episodes),
            "days_covered": len(day_counts),
            "avg_episodes_per_day": avg_daily,
            "day_distribution": dict(day_counts)
        }

    def memory_recall_pattern(self, agent_id: int) -> dict:
        """分析记忆召回模式"""
        # 从日志中提取 recall 事件
        log_file = self.exp_dir / "logs" / f"agent_{agent_id}.log"

        if not log_file.exists():
            return {}

        with open(log_file) as f:
            content = f.read()

        # 统计 recall 相关关键词
        recall_patterns = {
            "episodic_recall": content.count("episodic"),
            "summary_recall": content.count("summary"),
            "relationship_recall": content.count("relationship"),
            "total_recalls": content.count("recalling")
        }

        return recall_patterns

    def generate_memory_profile(self, agent_id: int) -> dict:
        """生成单个智能体的完整记忆画像"""
        return {
            "complexity": self.compute_memory_complexity(agent_id),
            "retention": self.memory_retention_analysis(agent_id),
            "recall_pattern": self.memory_recall_pattern(agent_id)
        }

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python memory_analyzer.py <exp_dir> [agent_id]")
        sys.exit(1)

    exp_dir = Path(sys.argv[1])
    agent_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    analyzer = MemoryAnalyzer(exp_dir)

    print(f"[INFO] Loading memory for agent {agent_id}...")
    analyzer.load_agent_memory(agent_id)

    profile = analyzer.generate_memory_profile(agent_id)

    import json
    print(json.dumps(profile, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

---

## 5. 预期结果格式

### 5.1 一致性分数表

```csv
treatment,phase_1_consistency,phase_2_consistency,cross_phase_similarity
memory_intact,0.78,0.82,0.65
memory_reset,0.45,0.52,0.32
memory_selective,0.65,0.68,0.48
memory_conflict,0.58,0.61,0.41
```

### 5.2 记忆复杂度分析

```json
{
  "agent_1": {
    "complexity": {
      "num_episodes": 45,
      "num_relationships": 12,
      "summary_length": 320,
      "avg_episode_length": 85
    },
    "retention": {
      "total_episodes": 45,
      "days_covered": 7,
      "avg_episodes_per_day": 6.4
    },
    "recall_pattern": {
      "episodic_recall": 23,
      "summary_recall": 15,
      "relationship_recall": 8
    }
  }
}
```

---

## 6. 时间规划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| Phase 1 | 脚本开发 + 预实验 | 1天 |
| Phase 2 | 运行全部4组实验（各14天） | 3天 |
| Phase 3 | 采访问答 + 数据分析 | 1天 |
| Phase 4 | 报告撰写 | 1天 |
| **总计** | | **6天** |

---

## 7. 与现有研究的对话

| 学术方向 | 相关研究 | 本实验如何贡献 |
|---------|---------|---------------|
| 记忆与一致性 | Hochreiter & Schmidhuber (1997) LSTM | 量化长期记忆对序列决策的影响 |
| LLM Agent 架构 | Park et al. (2023) *Generative Agents* | 验证多层次记忆架构的有效性 |
| 认知一致性 | Kahneman (2011) *Thinking, Fast and Slow* | 研究系统1/系统2在记忆召回中的角色 |

---

## 8. 扩展方向

### 8.1 遗忘机制研究

测试不同遗忘率对行为一致性的影响

### 8.2 记忆压缩优化

研究长期总结的更新频率对一致性的影响

### 8.3 跨智能体记忆同步

多个智能体的记忆如何相互影响和整合