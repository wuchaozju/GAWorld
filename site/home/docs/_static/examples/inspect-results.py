"""Read one resident's stress series and export a figure.
Usage: python inspect-results.py baseline-state.csv --agent 1
"""
import argparse
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser()
parser.add_argument('csv', type=Path)
parser.add_argument('--agent', type=int, default=1)
args = parser.parse_args()
state = pd.read_csv(args.csv)
required = {'agent_id', 'step', 'metric', 'value'}
if not required.issubset(state.columns):
    raise ValueError(f'Expected columns: {sorted(required)}')
series = state[(state.agent_id == args.agent) & (state.metric == 'stress')].sort_values('step')
if series.empty:
    raise ValueError(f'No stress records for agent {args.agent}')
print(series.to_string(index=False))
print(f'Final stress: {series.value.iloc[-1]:.3f}')
fig, ax = plt.subplots(figsize=(6, 3.4))
ax.plot(series.step, series.value, marker='o', color='#163b78')
ax.set(xlabel='Recorded step', ylabel='Stress (0–1)', ylim=(0, 1),
       title=f'Agent {args.agent}: stress')
ax.grid(alpha=0.2)
fig.tight_layout()
output = args.csv.parent / f'stress-agent-{args.agent}.svg'
fig.savefig(output)
print('Saved:', output)
