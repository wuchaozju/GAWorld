import csv
import json
from collections import defaultdict
import statistics

# Read CSV
data = defaultdict(lambda: defaultdict(list))
with open('docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        agent_id = int(row['agent_id'])
        step = int(row['step'])
        metric = row['metric']
        value = float(row['value'])
        data[agent_id][metric].append((step, value))

# Define wellbeing metrics and map to phases
# 580 steps over 3 days = ~193 steps/day
# Phase 1: steps 0-192 (Day 1), Phase 2: steps 193-385 (Day 2), Phase 3: steps 386-579 (Day 3)
def get_phase(step):
    if step <= 192:
        return 1
    elif step <= 385:
        return 2
    else:
        return 3

def get_day(step):
    return get_phase(step)

# Well-being metrics: emotion, stress, econ_security
wellbeing_metrics = ['emotion', 'stress', 'econ_security']

findings = {
    "simulation_summary": {
        "total_steps": 580,
        "days": 3,
        "agents": 5,
        "steps_per_day": 193
    },
    "wellbeing_by_day": {},
    "wellbeing_by_phase": {},
    "income_statistics": {},
    "key_patterns": []
}

# Compute wellbeing by day and phase
for metric in wellbeing_metrics:
    findings["wellbeing_by_day"][metric] = {}
    findings["wellbeing_by_phase"][metric] = {}

    for day in [1, 2, 3]:
        values = []
        phase = day
        for agent_id in range(1, 6):
            metric_data = data[agent_id][metric]
            for step, val in metric_data:
                if get_day(step) == day:
                    values.append(val)
        if values:
            findings["wellbeing_by_day"][metric][f"day_{day}"] = {
                "mean": round(statistics.mean(values), 4),
                "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "n": len(values)
            }

    for phase in [1, 2, 3]:
        values = []
        for agent_id in range(1, 6):
            metric_data = data[agent_id][metric]
            for step, val in metric_data:
                if get_phase(step) == phase:
                    values.append(val)
        if values:
            findings["wellbeing_by_phase"][metric][f"phase_{phase}"] = {
                "mean": round(statistics.mean(values), 4),
                "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "n": len(values)
            }

# Cross-agent comparisons
findings["cross_agent_comparison"] = {}
for metric in wellbeing_metrics:
    findings["cross_agent_comparison"][metric] = {}
    for agent_id in range(1, 6):
        values = [v for _, v in data[agent_id][metric]]
        if values:
            findings["cross_agent_comparison"][metric][f"agent_{agent_id}"] = {
                "mean": round(statistics.mean(values), 4),
                "trend_start": round(statistics.mean(values[:50]), 4),
                "trend_end": round(statistics.mean(values[-50:]), 4)
            }

# Identify key patterns
emotion_means_by_day = [findings["wellbeing_by_day"]["emotion"][f"day_{d}"]["mean"] for d in [1, 2, 3]]
stress_means_by_day = [findings["wellbeing_by_day"]["stress"][f"day_{d}"]["mean"] for d in [1, 2, 3]]
econ_means_by_day = [findings["wellbeing_by_day"]["econ_security"][f"day_{d}"]["mean"] for d in [1, 2, 3]]

findings["key_patterns"] = [
    f"Emotion trend: Day1={emotion_means_by_day[0]:.3f}, Day2={emotion_means_by_day[1]:.3f}, Day3={emotion_means_by_day[2]:.3f}",
    f"Stress trend: Day1={stress_means_by_day[0]:.3f}, Day2={stress_means_by_day[1]:.3f}, Day3={stress_means_by_day[2]:.3f}",
    f"Economic security trend: Day1={econ_means_by_day[0]:.3f}, Day2={econ_means_by_day[1]:.3f}, Day3={econ_means_by_day[2]:.3f}",
    f"Overall wellbeing trajectory: {'improving' if emotion_means_by_day[-1] > emotion_means_by_day[0] else 'declining'} over 3-day simulation"
]

if emotion_means_by_day[-1] > emotion_means_by_day[0]:
    findings["key_patterns"].append("Positive affect improved from Day 1 to Day 3")
else:
    findings["key_patterns"].append("Positive affect declined from Day 1 to Day 3")

if stress_means_by_day[-1] < stress_means_by_day[0]:
    findings["key_patterns"].append("Stress levels decreased over simulation")
else:
    findings["key_patterns"].append("Stress levels increased over simulation")

with open('docs/proposals/results/exp_macro_economy/run_42/shared_state.json', 'w') as f:
    json.dump(findings, f, indent=2)

print("Analysis complete. Results written to shared_state.json")