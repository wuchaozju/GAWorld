# Multi-Agent Research Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a multi-agent research team (Experimenter, Data Analyst, Paper Writer, Paper Reviewer) to collaboratively run exp_macro_economy (50-day simulation) and produce a research paper.

**Architecture:** Four agents share a Claude Sonnet model, communicate via shared filesystem (JSON state files), work sequentially: Experimenter → Data Analyst → Paper Writer → Paper Reviewer → back to Paper Writer if revisions needed.

**Tech Stack:** Python subprocess for simulation, pandas for analysis, JSON/MD for inter-agent communication.

---

## File Structure

```
docs/proposals/results/exp_macro_economy/run_42/
├── experiment_config.json        # Experimenter writes config
├── shared_state.json            # Inter-agent communication
├── state/agent_state_history.csv # Simulation output
├── economy/daily_ledger.csv      # Simulation output
├── wellbeing_analysis.json       # Data Analyst writes analysis
└── wellbeing_report.md          # Paper Writer writes final paper

docs/superpowers/
├── specs/2026-05-20-multi-agent-macro-economy-design.md  # Design doc
└── plans/2026-05-20-multi-agent-research-team.md        # This plan
```

---

## Agent Specifications

### Agent 1: Experimenter
- **Script**: `docs/proposals/experiments/run_experiment.py`
- **Command**: `python exp_macro_economy.py run --days 50 --seed 42`
- **Output**: Writes `experiment_config.json`, runs 50-day simulation

### Agent 2: Data Analyst
- **Reads**: `state/agent_state_history.csv`, `economy/daily_ledger.csv`
- **Outputs**: `wellbeing_analysis.json` with metrics
- **Validates**: Data completeness, macro phase coverage

### Agent 3: Paper Writer
- **Reads**: `wellbeing_analysis.json` from Data Analyst
- **Outputs**: `wellbeing_report.md` (research paper)
- **Sections**: Introduction, Methods, Results, Discussion

### Agent 4: Paper Reviewer
- **Reads**: `wellbeing_report.md`
- **Checks**: Data citations, logical flow, conclusions
- **Outputs**: Revision notes in `shared_state.json["revisions"]`

### Shared State File Schema (`shared_state.json`)
```json
{
  "simulation_status": "pending" | "running" | "completed" | "failed",
  "data_validation_status": "pending" | "passed" | "failed",
  "paper_draft_status": "in_progress" | "review" | "approved" | "needs_revision",
  "current_phase": 1 | 2 | 3 | 4,
  "findings": {},
  "revisions": []
}
```

---

## Task 1: Initialize Shared State

**Files:**
- Create: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`

- [ ] **Step 1: Create shared_state.json**

```json
{
  "simulation_status": "pending",
  "data_validation_status": "pending",
  "paper_draft_status": "pending",
  "current_phase": 1,
  "findings": {},
  "revisions": []
}
```

- [ ] **Step 2: Commit**

```bash
mkdir -p docs/proposals/results/exp_macro_economy/run_42
echo '{"simulation_status":"pending","data_validation_status":"pending","paper_draft_status":"pending","current_phase":1,"findings":{},"revisions":[]}' > docs/proposals/results/exp_macro_economy/run_42/shared_state.json
git add docs/proposals/results/exp_macro_economy/run_42/shared_state.json
git commit -m "feat: initialize shared state for multi-agent research team"
```

---

## Task 2: Experimenter Runs 50-Day Simulation

**Files:**
- Modify: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`
- Create: `docs/proposals/results/exp_macro_economy/run_42/experiment_config.json`

- [ ] **Step 1: Update shared_state.json - simulation_status: "running"**

```json
{"simulation_status": "running"}
```

- [ ] **Step 2: Run experiment**

```bash
cd /Users/cw/dev/GAWorld && python docs/proposals/experiments/exp_macro_economy.py run --days 50 --seed 42
```

- [ ] **Step 3: Verify simulation outputs exist**

```bash
ls docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv
ls docs/proposals/results/exp_macro_economy/run_42/economy/daily_ledger.csv
```

Expected: Both files exist with data

- [ ] **Step 4: Update shared_state.json - simulation_status: "completed"**

```json
{"simulation_status": "completed"}
```

- [ ] **Step 5: Commit**

```bash
git add docs/proposals/results/exp_macro_economy/run_42/
git commit -m "feat: experimenter completes 50-day simulation"
```

---

## Task 3: Data Analyst Validates and Computes Metrics

**Files:**
- Read: `docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv`
- Read: `docs/proposals/results/exp_macro_economy/run_42/economy/daily_ledger.csv`
- Create: `docs/proposals/results/exp_macro_economy/run_42/wellbeing_analysis.json`
- Modify: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`

- [ ] **Step 1: Validate data files exist and have content**

```bash
wc -l docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv
wc -l docs/proposals/results/exp_macro_economy/run_42/economy/daily_ledger.csv
```

Expected: Both have > 50 lines (one header + data rows)

- [ ] **Step 2: Compute wellbeing analysis**

```python
import pandas as pd
import json

state_df = pd.read_csv("docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv")
ledger_df = pd.read_csv("docs/proposals/results/exp_macro_economy/run_42/economy/daily_ledger.csv")

# Compute wellbeing by phase (phase 1 = day 1-30, phase 2 = day 31-50)
state_df["macro_phase"] = (state_df["day"] - 1) // 30 + 1

wellbeing_metrics = ["emotion", "stress", "econ_security"]
findings = {}

for metric in wellbeing_metrics:
    if metric in state_df.columns:
        phase_agg = state_df.groupby("macro_phase")[metric].agg(["mean", "std"]).to_dict()
        findings[f"{metric}_by_phase"] = phase_agg

# Income stats
if "income" in ledger_df.columns:
    findings["avg_income"] = float(ledger_df["income"].mean())
    findings["income_by_phase"] = ledger_df.groupby("macro_phase")["income"].agg(["mean", "std"]).to_dict()

# Agent count
findings["n_agents"] = int(state_df["agent_id"].nunique())
findings["n_days"] = int(state_df["day"].nunique())

analysis = {
    "findings": findings,
    "n_records": len(state_df),
    "macro_phases_covered": sorted(state_df["macro_phase"].unique().tolist())
}

with open("docs/proposals/results/exp_macro_economy/run_42/wellbeing_analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)

print(json.dumps(analysis, indent=2))
```

- [ ] **Step 3: Verify wellbeing_analysis.json created**

```bash
cat docs/proposals/results/exp_macro_economy/run_42/wellbeing_analysis.json
```

- [ ] **Step 4: Update shared_state.json - data_validation_status: "passed"**

```json
{
  "data_validation_status": "passed",
  "findings": { ... the computed findings ... }
}
```

- [ ] **Step 5: Commit**

```bash
git add docs/proposals/results/exp_macro_economy/run_42/wellbeing_analysis.json
git commit -m "feat: data analyst computes wellbeing metrics"
```

---

## Task 4: Paper Writer Drafts Research Paper

**Files:**
- Read: `docs/proposals/results/exp_macro_economy/run_42/wellbeing_analysis.json`
- Create: `docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md`
- Modify: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`

- [ ] **Step 1: Read wellbeing_analysis.json**

```bash
cat docs/proposals/results/exp_macro_economy/run_42/wellbeing_analysis.json
```

- [ ] **Step 2: Write wellbeing_report.md**

```markdown
# 宏观经济周期与居民福祉研究报告

**实验配置：** 50天仿真，seed=42

---

## 1. 研究问题

本研究探讨宏观经济周期（扩张→峰值→收缩→谷底）如何影响居民的情绪、压力和经济安全感。

---

## 2. 实验方法

- **仿真平台：** GAWorld
- **智能体数量：** 5
- **仿真时长：** 50天
- **宏观阶段：** 每阶段约30天（50天覆盖约1-2个完整阶段）

---

## 3. 主要发现

### 3.1 情绪（Emotion）变化

| 宏观阶段 | 平均值 | 标准差 |
|---------|--------|--------|
| Phase 1 (Day 1-30) | 见数据 | 见数据 |
| Phase 2 (Day 31-50) | 见数据 | 见数据 |

### 3.2 压力（Stress）变化

[同上格式]

### 3.3 经济安全感（Econ Security）变化

[同上格式]

---

## 4. 讨论与政策建议

[基于数据填写]

---

## 5. 结论

[总结研究发现]
```

- [ ] **Step 3: Update shared_state.json - paper_draft_status: "review"**

```json
{"paper_draft_status": "review"}
```

- [ ] **Step 4: Commit**

```bash
git add docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md
git commit -m "feat: paper writer completes draft"
```

---

## Task 5: Paper Reviewer Reviews Draft

**Files:**
- Read: `docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md`
- Read: `docs/proposals/results/exp_macro_economy/run_42/wellbeing_analysis.json`
- Modify: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`

- [ ] **Step 1: Review paper for logical consistency and data citations**

Check:
- All numbers in paper match wellbeing_analysis.json
- Conclusions supported by data
- Logical flow (Intro → Methods → Results → Discussion)

- [ ] **Step 2: If revisions needed, add to shared_state.json**

```json
{
  "paper_draft_status": "needs_revision",
  "revisions": [
    "Check: emotion mean in Phase 1 matches actual data",
    "Fix: Add income statistics to Results section"
  ]
}
```

- [ ] **Step 3: If approved, update shared_state.json**

```json
{"paper_draft_status": "approved"}
```

- [ ] **Step 4: Commit**

```bash
git add docs/proposals/results/exp_macro_economy/run_42/shared_state.json
git commit -m "feat: paper reviewer completes review"
```

---

## Task 6: Finalize Paper (if revisions needed)

**Files:**
- Modify: `docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md`
- Modify: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`

- [ ] **Step 1: Read revisions from shared_state.json**

```bash
cat docs/proposals/results/exp_macro_economy/run_42/shared_state.json | jq .revisions
```

- [ ] **Step 2: Apply revisions to wellbeing_report.md**

[Address each revision item]

- [ ] **Step 3: Update shared_state.json - paper_draft_status: "approved"**

```json
{"paper_draft_status": "approved"}
```

- [ ] **Step 4: Commit**

```bash
git add docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md docs/proposals/results/exp_macro_economy/run_42/shared_state.json
git commit -m "feat: paper finalized with revisions"
```

---

## Success Criteria Checklist

- [ ] 50-day simulation completes
- [ ] Macro phases (1-2) have data coverage
- [ ] Wellbeing metrics computed (emotion, stress, econ_security)
- [ ] Paper draft written
- [ ] Paper reviewer approves (or revisions applied)

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-20-multi-agent-research-team.md`**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**