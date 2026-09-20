# Multi-Agent Research Team Design: exp_macro_economy

**Date: 2026-05-20**

## Overview

A multi-agent research team using shared Claude Sonnet model to collaboratively run exp_macro_economy (50-day simulation) and produce a research paper on macroeconomic cycles and resident wellbeing.

## Team Composition

| Role | Agent ID | Responsibility |
|------|----------|---------------|
| **Experimenter** | agent_1 | Execute 50-day simulation, monitor progress, handle errors |
| **Data Analyst** | agent_2 | Validate output data, detect anomalies, compute statistics |
| **Paper Writer** | agent_3 | Draft research paper sections, organize findings |
| **Paper Reviewer** | agent_4 | Review paper logic, check data citations, suggest improvements |

All agents share the same Claude Sonnet model but have independent task contexts.

## Experiment Configuration

- **Experiment**: exp_macro_economy
- **Duration**: 50 days (compression from original 150)
- **Seed**: 42
- **Output**: `docs/proposals/results/exp_macro_economy/run_42/`

Note: 50 days covers ~2-3 macro phases (each phase = 30 days), sufficient for preliminary analysis.

## Workflow

```
Experimenter
  ├─ Run simulation (50 days)
  ├─ Monitor progress (daily checkpoints)
  └─ Report completion

Data Analyst
  ├─ Validate ledger.csv exists and has data
  ├─ Validate agent_state_history.csv
  ├─ Check macro phase coverage (day 1-30, day 31-50)
  └─ Compute wellbeing metrics (emotion, stress, econ_security)

Paper Writer
  ├─ Write Introduction & Methods
  ├─ Document key findings from Data Analyst
  └─ Draft Discussion & Policy Recommendations

Paper Reviewer
  ├─ Review logical flow
  ├─ Verify data citations
  └─ Propose revisions → back to Paper Writer
```

## Communication Protocol

- All agents communicate via shared filesystem
- Shared state file: `docs/proposals/results/exp_macro_economy/run_42/shared_state.json`
- Shared state fields:
  - `simulation_status`: "running" | "completed" | "failed"
  - `data_validation_status`: "pending" | "passed" | "failed"
  - `paper_draft_status`: "in_progress" | "review" | "approved"
  - `current_phase`: 1 | 2
  - `findings`: {}

## Output Artifacts

1. `experiment_config.json` - Experiment parameters
2. `wellbeing_analysis.json` - Computed statistics
3. `wellbeing_report.md` - Research paper

## Agent Task Prompts

### Experimenter
```
Run exp_macro_economy with:
- Days: 50
- Seed: 42
- Output dir: docs/proposals/results/exp_macro_economy/run_42/

After completion, update shared_state.json with simulation_status: "completed"
```

### Data Analyst
```
After experimenter completes:
1. Read ledger.csv and agent_state_history.csv
2. Validate data completeness
3. Compute wellbeing metrics by macro phase (day 1-30 vs day 31-50)
4. Save findings to shared_state.json["findings"]
5. Update shared_state.json["data_validation_status"]: "passed"
```

### Paper Writer
```
After data analyst completes:
1. Read findings from shared_state.json
2. Write paper sections:
   - Introduction (research question, motivation)
   - Methods (50-day sim, macro cycle phases)
   - Results (wellbeing by phase, income quartile analysis)
   - Discussion (implications, policy recommendations)
3. Save draft to wellbeing_report.md
4. Update shared_state.json["paper_draft_status"]: "review"
```

### Paper Reviewer
```
After paper writer completes:
1. Read wellbeing_report.md
2. Check:
   - All data citations match actual numbers
   - Logical flow is coherent
   - Conclusions supported by data
3. If revisions needed:
   - Write revision notes to shared_state.json["revisions"]
   - Update shared_state.json["paper_draft_status"]: "in_progress"
4. If approved:
   - Update shared_state.json["paper_draft_status"]: "approved"
```

## Success Criteria

- [ ] 50-day simulation completes without error
- [ ] Both macro phases (day 1-30, day 31-50) have data
- [ ] Wellbeing metrics computed (emotion, stress, econ_security by phase)
- [ ] Paper draft written and approved by reviewer
- [ ] Final report saved to wellbeing_report.md