"""End-of-run charts and the state-history table.

Moved out of ``generative_city_sim.py`` (REFACTOR_PLAN stage 1) unchanged;
the simulator re-exports every name, so ``generative_city_sim.<name>``
keeps working.
"""

import json
import os

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd


def visualize_social_network(agents, step=None, output_dir="output/network", node_color_attr=None):
    """
    agents:
        - dict: {agent_id: agent_dict}
        - or list: [agent_dict, ...]
    agent_dict 中建议包含：
        - "id" 或 "name"
        - "friends" / "social_connections"
    """

    os.makedirs(output_dir, exist_ok=True)

    G = nx.Graph()

    # ---------- 统一 agent 访问方式 ----------
    if isinstance(agents, dict):
        agent_items = agents.items()
    else:  # list
        agent_items = [(a.get("id", str(i)), a) for i, a in enumerate(agents)]

    # ---------- 加节点 ----------
    for agent_id, agent in agent_items:
        value = agent.get(node_color_attr, 0.5) if node_color_attr else 0.5
        G.add_node(agent_id, value=value)

    # ---------- 加边 ----------
    for agent_id, agent in agent_items:
        friends = agent.get("friends") or agent.get("social_connections") or []
        for f in friends:
            if G.has_node(f):
                G.add_edge(agent_id, f)

    # ---------- 布局 ----------
    pos = nx.spring_layout(G, seed=42)

    node_values = [G.nodes[n]["value"] for n in G.nodes]

    plt.figure(figsize=(8, 8))
    nodes = nx.draw_networkx_nodes(G, pos, node_size=300, node_color=node_values, cmap=plt.cm.YlGn)
    nx.draw_networkx_edges(G, pos, alpha=0.4)
    nx.draw_networkx_labels(G, pos, font_size=8)

    if node_color_attr:
        plt.colorbar(nodes, label=node_color_attr)

    title = "Social Network"
    if step is not None:
        title += f" (Step {step})"
    plt.title(title)

    plt.axis("off")

    filename = "social_network.png" if step is None else f"social_network_{step:03d}.png"
    plt.savefig(os.path.join(output_dir, filename), dpi=200)
    plt.close()


def visualize_agent_state_changes(
    state_history,
    agent_names,
    output_dir="output/state",
    metrics=None,
):
    os.makedirs(output_dir, exist_ok=True)
    if not metrics:
        sample_history = next(iter(state_history.values()), {})
        metrics = list(sample_history.keys())

    if not metrics:
        return

    cols = 3 if len(metrics) > 4 else 2
    rows = int(np.ceil(len(metrics) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4.2, rows * 3.2), sharex=True)
    axes = np.array(axes).reshape(-1)

    for i, metric in enumerate(metrics):
        ax = axes[i]
        for agent_id, history in state_history.items():
            series = history.get(metric, [])
            label = agent_names.get(agent_id, str(agent_id))
            # Series lengths differ once an agent is removed mid-run (K5);
            # each series plots against its own step range.
            ax.plot(range(len(series)), series, label=label, linewidth=1.6)
        ax.set_title(metric)
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.2)

    for j in range(len(metrics), len(axes)):
        axes[j].axis("off")

    axes[0].legend(loc="upper right", fontsize=8)
    fig.suptitle("Agent State Changes Over Time")
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    out_path = os.path.join(output_dir, "agent_state_over_time.png")
    plt.savefig(out_path, dpi=200)
    plt.close()


def save_state_history(state_history, output_dir="output/state"):
    os.makedirs(output_dir, exist_ok=True)
    rows = []
    for agent_id, history in state_history.items():
        for metric, series in history.items():
            for step, value in enumerate(series):
                rows.append(
                    {
                        "agent_id": agent_id,
                        "step": step,
                        "metric": metric,
                        "value": float(value),
                    }
                )
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "agent_state_history.csv"), index=False)


def append_jsonl(path, row):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
