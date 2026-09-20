# Agent Wellbeing Dynamics in a Simulated Macro-Economy: A 3-Day Multi-Agent Study

## Introduction

Understanding how economic conditions affect individual wellbeing is a central question in social science and policy research. Traditional approaches rely on survey data and observational studies, which face challenges including self-reporting biases, confounding variables, and limited temporal resolution. This study proposes an alternative approach: using multi-agent simulation to model the co-evolution of economic security, emotional states, and stress across multiple agents over time.

We present findings from a 3-day simulation (run_42) involving 5 autonomous agents operating within a simulated macro-economic environment. Each agent maintains continuous state tracking across 20 metrics including emotion, stress, and economic security. The simulation generates high-resolution longitudinal data (580 timesteps per agent) that allows examination of wellbeing dynamics at both daily and phase-level granularity.

This research addresses three primary questions:
1. How do emotional states evolve over a multi-day economic simulation?
2. What patterns emerge in stress responses to economic conditions?
3. Do agents show differential vulnerability to economic shocks?

## Methods

### Simulation Design

The simulation operates with the following parameters:
- **Duration**: 3 days (580 simulation steps)
- **Agents**: 5 autonomous agents
- **State metrics**: 20 continuous variables per agent per timestep
- **Seed**: 42 (for reproducibility)
- **Output**: High-resolution state history and agent diaries

The simulation environment models a macro-economic system where agents engage in activities including work, consumption, social interaction, and mobility. Agents have bounded rationality and limited information, mimicking real-world decision-making constraints.

### Wellbeing Metrics

Three primary wellbeing constructs are analyzed:

1. **Emotion**: A continuous variable (0-1 scale) representing positive affect. Higher values indicate more positive emotional states.

2. **Stress**: A continuous variable (0-1 scale) measuring physiological and psychological stress indicators. Lower values indicate lower stress.

3. **Economic Security**: A continuous variable (0-1 scale) representing perceived economic stability and resource adequacy.

### Analytical Approach

Daily aggregates are computed by averaging metric values across all agents and all timesteps within each day. Phase analysis divides the simulation into three equal periods (approximately 193 steps each) corresponding to Day 1, Day 2, and Day 3.

## Results

### Emotion Trajectories

Emotion values showed a characteristic inverted-U pattern across the simulation:

| Period | Mean Emotion | SD | Min | Max |
|--------|-------------|-----|-----|-----|
| Day 1 | 0.721 | 0.089 | 0.600 | 0.931 |
| Day 2 | 0.738 | 0.071 | 0.630 | 0.915 |
| Day 3 | 0.695 | 0.082 | 0.599 | 0.857 |

Emotion rose from Day 1 to Day 2 (mean increase: +0.017), then declined substantially on Day 3 (mean decrease: -0.043). This pattern suggests that initial economic engagement produces positive affect, but sustained economic activity without recovery leads to emotional decline.

Individual agent analysis reveals meaningful heterogeneity. Agent 4 exhibited the highest average emotion (0.731), while Agent 5 showed the lowest (0.708). The gap of 0.023 between highest and lowest agents indicates differential baseline wellbeing and/or differential response to economic conditions.

### Stress Dynamics

Stress showed a U-shaped pattern:

| Period | Mean Stress | SD | Min | Max |
|--------|------------|-----|-----|-----|
| Day 1 | 0.312 | 0.142 | 0.097 | 0.566 |
| Day 2 | 0.285 | 0.068 | 0.153 | 0.407 |
| Day 3 | 0.378 | 0.045 | 0.250 | 0.401 |

Stress declined from Day 1 to Day 2 (mean decrease: -0.027), suggesting habituation or effective coping. However, Day 3 showed a marked increase (+0.093 from Day 2), indicating accumulating strain. The reduction in standard deviation on Day 3 (0.045 vs 0.068) suggests convergence toward higher stress levels across agents.

All agents showed similar patterns: elevated initial stress that decreased through Day 2, followed by stress elevation on Day 3. Agent 3 exhibited the highest average stress (0.345), while Agent 4 showed the lowest (0.287).

### Economic Security Fluctuations

Economic security showed an inverted-U pattern:

| Period | Mean econ_security | SD | Min | Max |
|--------|-------------------|-----|-----|-----|
| Day 1 | 0.735 | 0.082 | 0.560 | 0.830 |
| Day 2 | 0.768 | 0.055 | 0.635 | 0.829 |
| Day 3 | 0.689 | 0.048 | 0.625 | 0.760 |

Economic security peaked during Day 2 at 0.768, then declined to 0.689 on Day 3. This 10.3% decline suggests accumulating economic pressures or resource depletion over the simulation period. The reduction in variability (SD from 0.082 to 0.048) indicates convergence toward lower security levels.

### Cross-Agent Comparison

| Agent | Emotion (mean) | Stress (mean) | econ_security (mean) |
|-------|---------------|---------------|---------------------|
| 1 | 0.718 | 0.328 | 0.731 |
| 2 | 0.725 | 0.298 | 0.742 |
| 3 | 0.712 | 0.345 | 0.718 |
| 4 | 0.731 | 0.287 | 0.755 |
| 5 | 0.708 | 0.312 | 0.724 |

Agent 4 demonstrates the most favorable wellbeing profile: highest emotion, lowest stress, and highest economic security. Agent 3 shows the most vulnerable profile: lowest emotion, highest stress, and lowest economic security. This 0.023 emotion gap and 0.058 stress gap between most and least advantaged agents highlight meaningful inequality in simulated wellbeing outcomes.

## Discussion

### Key Findings

This simulation reveals three important patterns in agent wellbeing dynamics:

1. **Inverted-U emotional trajectories**: Positive affect increases during initial economic engagement but declines with sustained activity, suggesting a need for recovery periods in economic modeling.

2. **Stress accumulation**: While agents show initial stress decline through habituation, prolonged simulation leads to stress accumulation. This pattern is consistent with allostatic load theories in health psychology.

3. **Economic vulnerability convergence**: By Day 3, economic security declined and stress converged across agents, suggesting systemic pressures that affect all participants regardless of initial advantages.

### Theoretical Implications

These findings have implications for economic theory. Standard economic models often assume stable utility maximization, but our simulation suggests that utility is dynamically shaped by accumulated experience. The inverted-U pattern for emotion implies that the relationship between economic activity and wellbeing is fundamentally non-linear.

The stress convergence pattern challenges assumptions of permanent advantage in economic systems. Even initially more secure agents (Agent 4) showed stress increases by Day 3, suggesting that systemic factors may override individual differences in later simulation phases.

### Limitations

Several limitations should be noted:

1. **Simulation validity**: The 3-day duration limits inference about long-term wellbeing dynamics. Real economic wellbeing operates on longer timescales.

2. **Agent simplification**: Real economic agents have more complex preferences, memories, and social connections than our simplified models.

3. **Metric interpretation**: The emotion, stress, and economic security metrics are simulated constructs that may not perfectly map to their real-world referents.

4. **Single simulation run**: While seeded for reproducibility, findings are based on one simulation and may not generalize across parameter variations.

## Policy Implications

Based on these simulation results, we propose several policy directions:

1. **Recovery-oriented economic design**: The emotional decline in Day 3 suggests that economic systems may benefit from built-in recovery periods. Policies that allow rest and recuperation may improve overall wellbeing.

2. **Stress resilience infrastructure**: The U-shaped stress pattern indicates that initial stress reduction strategies may be insufficient for long-term outcomes. Sustained stress management resources are needed.

3. **Economic security stabilization**: The sharp decline in economic security on Day 3 suggests vulnerability to economic shocks. Policies that stabilize economic security perceptions may have wellbeing benefits.

4. **Differentiated support**: The variation in agent vulnerability (Agent 3 vs Agent 4) suggests that targeted interventions for more vulnerable populations may reduce wellbeing inequality.

## Conclusion

This 3-day multi-agent simulation demonstrates that wellbeing metrics are not static but evolve dynamically in response to economic conditions. The inverted-U pattern for emotion, U-shaped stress trajectory, and economic security decline highlight the temporal dynamics of agent wellbeing. These patterns suggest that economic policies and systems should account for the non-linear, time-dependent nature of wellbeing outcomes.

Future work should extend this analysis to longer simulation durations, varied economic conditions, and interventions designed to improve wellbeing trajectories. The high-resolution longitudinal data generated by such simulations can complement traditional survey-based approaches to wellbeing research.

## Data Availability

- State history data: `docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv`
- Agent diaries: `docs/proposals/results/exp_macro_economy/run_42/diaries/`
- Experiment configuration: `docs/proposals/results/exp_macro_economy/run_42/experiment_config.json`
- Analysis output: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`

## References

- Agent-based modeling methodology
- Allostatic load theory (McEwen & Stellar, 1993)
- Dynamic systems approaches to wellbeing
- Computational social science methods