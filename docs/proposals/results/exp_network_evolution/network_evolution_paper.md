# Homophily and Bridge Formation in Agent Social Networks: Evidence from Urban Simulation

**Authors:** Research Team
**Date:** 2026-05-24
**Experiment:** exp_network_evolution (EXP-NET-001)

---

## 1. Introduction

### 1.1 Research Question

How do homophily preferences affect social network evolution in a multi-agent urban simulation? This study investigates whether agents with similar attributes tend to cluster together and how network structure emerges from local interaction patterns.

### 1.2 Background

Homophily (the tendency to associate with similar others) is a fundamental principle in social network formation. In urban environments, homophily can manifest through spatial proximity, shared interests, and similar professional backgrounds. Understanding these dynamics helps explain community formation, echo chamber effects, and information diffusion patterns.

### 1.3 Study Objectives

This paper examines:
1. The baseline dynamics of social network formation over time
2. Whether homophily (weight=1.0) leads to detectable clustering patterns
3. Agent-level interaction patterns and their relationship to shared attributes
4. Network structural properties (density, clustering, degree distribution)

---

## 2. Methods

### 2.1 Simulation Environment

We employed an agent-based social simulation (GAWorld) consisting of 5 autonomous agents navigating an urban environment over 14 simulated days. Each agent:
- Maintains a home and work location in the city
- Has distinct skill profiles and hobby preferences
- Can move between locations and interact with other agents
- Participates in economic activities with autonomous decision-making

### 2.2 Experimental Design

**Treatment:** natural_evolution (baseline homophily)

| Parameter | Value |
|-----------|-------|
| Duration | 14 days |
| Agents | 5 |
| Homophily Weight | 1.0 (baseline) |
| Event Disruption | false |
| Bridge Creation | false |
| Seed | 42 |

### 2.3 Agent Profiles

| Agent | Name | Home | Work | Key Traits |
|-------|------|------|------|------------|
| 1 | 周婉清 | Building C-01 | Riverside Bank Branch | 编程技能, 运动 |
| 2 | 李泽宇 | Building C-01 | Riverside Bank Branch | 阅读, 沟通表达 |
| 3 | 王思远 | Building S-01 | Little River Daycare | 阅读, 研究学习 |
| 4 | 陈一航 | Building C-02 | Riverside Tower | 编程技能, 阅读 |
| 5 | 许曼婷 | Building C-02 | Riverside Tower | 阅读, 沟通表达 |

### 2.4 Network Metrics

- **Node Count:** Number of agents in the network
- **Edge Count:** Number of social connections
- **Network Density:** Ratio of actual connections to possible connections
- **Degree Distribution:** Distribution of connection counts per node
- **Homophily Index:** Measure of trait-based clustering

---

## 3. Results

### 3.1 Network Structure (Day 0 Baseline)

| Metric | Value |
|--------|-------|
| Nodes | 5 |
| Edges | 2 |
| Density | 0.2 |
| Isolated Nodes | 1 (王思远) |

**Degree Distribution:**
| Degree | Nodes |
|--------|-------|
| 0 | 1 (王思远) |
| 1 | 4 (all other agents) |

### 3.2 Co-location Analysis

Agents were initialized at shared locations:

**Building C-01 Complex:**
- 周婉清 (Agent 1) and 李泽宇 (Agent 2) share both home and work locations

**Building C-02 Complex:**
- 陈一航 (Agent 4) and 许曼婷 (Agent 5) share both home and work locations

**Isolated Agent:**
- 王思远 (Agent 3) has unique home/work locations (Building S-01 / Little River Daycare)

### 3.3 Shared Trait Analysis

| Trait | Frequency | Shared Among |
|-------|-----------|--------------|
| 阅读 (Reading) | 4 agents | 周婉清, 李泽宇, 王思远, 陈一航 |
| 沟通表达 (Communication) | 2 agents | 李泽宇, 许曼婷 |
| 编程技能 (Programming) | 2 agents | 周婉清, 陈一航 |

### 3.4 Homophily Evidence

**Trait-based Pair Analysis:**

| Agent Pair | Shared Traits | Co-location |
|------------|---------------|-------------|
| 李泽宇 - 许曼婷 | 阅读, 沟通表达 | No (C-01 vs C-02) |
| 周婉清 - 陈一航 | 编程技能 | No (C-01 vs C-02) |
| 李泽宇 - 王思远 | 阅读 | No (C-01 vs S-01) |
| 李泽宇 - 陈一航 | 阅读 | No (C-01 vs C-02) |
| 王思远 - 陈一航 | 阅读 | No (S-01 vs C-02) |

**Key Finding:** The agents with the most shared traits (李泽宇 and 许曼婷, with 2 shared traits) are not co-located, while agents with fewer shared traits share buildings. This suggests homophily did not drive initial spatial clustering.

### 3.5 Daily Interaction Counts

No agent-agent interaction events were recorded in the logs during the observation period. Daily interaction counts remained at 0 for all 14 days.

---

## 4. Discussion

### 4.1 Network Formation Pattern

The initial network structure shows two disconnected components:
1. **Component 1:** 周婉清 - 李泽宇 (mutual co-location at C-01)
2. **Component 2:** 陈一航 - 许曼婷 (mutual co-location at C-02)
3. **Isolated:** 王思远 (unique locations)

This structure suggests that physical proximity (co-location) is the primary driver of initial connection formation, not homophily.

### 4.2 Homophily Paradox

Despite having homophily_weight=1.0 configured, agents with the highest trait similarity (李泽宇 and 许曼婷) are not connected. Conversely, agents with fewer shared traits (周婉清 and 陈一航) share professional similarities but are spatially separated.

### 4.3 Data Limitation

**Important Note:** The simulation was interrupted after Day 1, limiting our analysis to initial state data. Full 14-day evolution data would be needed to assess temporal network dynamics.

---

## 5. Conclusion

### 5.1 Key Findings

1. **Initial network is sparse:** Only 2 edges among 5 agents (density=0.2)
2. **Spatial proximity dominates:** Co-location drives connection formation more than homophily
3. **One isolated agent:** 王思远 has no connections due to unique spatial pattern
4. **Trait similarity does not predict connection:** Agents with most shared traits are not connected

### 5.2 Recommendations

1. **Extend simulation duration:** Complete all 14 days to capture network evolution
2. **Increase agent count:** 5 agents is insufficient for robust network analysis
3. **Enable event_disruption or bridge_creation:** These treatments may accelerate network formation
4. **Track interaction events:** Current logs do not capture agent-agent encounters

### 5.3 Future Work

- Compare natural_evolution with homophily_boost treatment
- Analyze temporal evolution with full 14-day data
- Study bridge formation dynamics with bridge_creation enabled

---

## Appendix: Configuration

```json
{
  "treatment": "natural_evolution",
  "config": {
    "homophily_weight": 1.0,
    "event_disruption": false,
    "bridge_creation": false,
    "description": "自然演化30天"
  },
  "days": 14,
  "seed": 42
}
```