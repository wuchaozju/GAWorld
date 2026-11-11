"""Finite policies. decide() has no task truth, scorer or feedback parameter."""

import copy

from . import environment
from .protocol import digest


def initial_state():
    return {"private": [{}, {}, {}], "organization": {}}


def branch(state, turnover, memory):
    result = copy.deepcopy(state)
    if turnover:
        result["private"] = [{}, {}, {}]
    if not memory:
        result["organization"] = {}
    return result


def quality(counts):
    a, b = counts or [2, 2]
    return a / (a + b)


def update(container, key, good):
    counts = container.setdefault(key, [2, 2])
    counts[0 if good else 1] += 1


def best(values):
    return max(range(4), key=lambda i: (values[i], -i))


def decide(views, state, procedure, memory, check):
    """check is the sole bounded observation capability; all estimates use visible evidence."""
    common = views[0]["common"]["values"]
    source = views[0]["source"]
    shared_q = quality(state["organization"].get(source)) if memory else 0.5
    actions = []

    def action(kind, **values):
        identifier = f"{views[0]['task_id']}:action:{len(actions)}"
        actions.append(
            {"id": identifier, "kind": kind, "depends_on": [actions[-1]["id"]] if actions else [], **values}
        )

    private_q = [quality(p.get("local")) for p in state["private"]]
    if not procedure:
        votes = []
        for role, view in enumerate(views):
            # Roles cannot use anyone else's private observation in proposal voting.
            estimates = [list(row) for row in common]
            weight = private_q[role] / (private_q[role] + shared_q)
            estimates[role] = [
                weight * a + (1 - weight) * b
                for a, b in zip(view["local"]["values"], common[role], strict=True)
            ]
            vote = best([sum(row[i] for row in estimates) for i in range(4)])
            votes.append(vote)
            action("VOTE", role=role, option=vote)
        choice = max(range(4), key=lambda i: (votes.count(i), -i))
        return (
            choice,
            actions,
            {
                "messages": 3,
                "checks": 0,
                "local_reports_shared": 0,
                "common_report_duplicates_removed": 0,
                "corrections": 0,
            },
        )

    ledger = {}
    for role, view in enumerate(views):
        for evidence in (view["local"], view["common"]):
            action("REPORT", role=role, evidence_id=evidence["id"], values=evidence["values"])
            ledger[evidence["id"]] = evidence  # Repeated common source counts once.
    estimates, disagreement = [], []
    for role, view in enumerate(views):
        weight = private_q[role] / (private_q[role] + shared_q)
        estimates.append(
            [
                weight * a + (1 - weight) * b
                for a, b in zip(view["local"]["values"], common[role], strict=True)
            ]
        )
        disagreement.append(
            sum(abs(a - b) for a, b in zip(view["local"]["values"], common[role], strict=True)) / 4
        )
    checks, corrections = 0, 0
    for role in sorted(range(3), key=lambda r: (-disagreement[r], r)):
        # Predeclared finite heuristic, without knowing whether verification will pay off.
        if checks >= 2 or views[0]["check_cost"] >= 2 or disagreement[role] <= 1:
            continue
        previous = best(estimates[role])
        values = check(role, checks)
        estimates[role] = values
        checks += 1
        corrections += int(previous != best(values))
        action("CHECK", role=role, evidence_id=views[role]["local"]["id"], values=values)
    choice = best([sum(row[i] for row in estimates) for i in range(4)])
    action("DECIDE", option=choice, evidence_ids=sorted(ledger))
    return (
        choice,
        actions,
        {
            "messages": 6,
            "checks": checks,
            "local_reports_shared": sum(
                a["kind"] == "REPORT" and ":local:" in a["evidence_id"] for a in actions
            ),
            "common_report_duplicates_removed": sum(a["kind"] == "REPORT" for a in actions) - len(ledger),
            "corrections": corrections,
        },
    )


def episode(task, state, procedure, memory, training):
    visible = environment.views(task)
    next_state = branch(state, False, memory)
    checks_used = 0

    def check(role, _used):
        nonlocal checks_used
        values = environment.verify(task, role, checks_used)
        checks_used += 1
        return values

    choice, actions, metrics = decide(visible, next_state, procedure, memory, check)
    cost = (
        metrics["messages"] * 0.08 + metrics["checks"] * task["check_cost"] + (1 + metrics["checks"]) * 0.04
    )
    outcome = environment.score(task, choice)
    if training:
        observed = environment.feedback(task, choice)
        for role, private in enumerate(next_state["private"]):
            update(private, "local", abs(visible[role]["local"]["values"][choice] - observed[role]) <= 1)
        if memory:
            good = sum(abs(visible[0]["common"]["values"][r][choice] - observed[r]) for r in range(3)) <= 3
            update(next_state["organization"], visible[0]["source"], good)
        actions.append(
            {
                "id": f"{task['id']}:feedback",
                "kind": "FEEDBACK",
                "depends_on": [actions[-1]["id"]],
                "option": choice,
                "values": observed,
            }
        )
    return {
        "input_hash": task["input_hash"],
        "choice": choice,
        **outcome,
        **metrics,
        "cost": cost,
        "net_reward": outcome["reward"] - cost,
        "budget_violations": int(metrics["messages"] > 6 or metrics["checks"] > 2),
        "delay_steps": 1 + metrics["checks"],
        "stratum": task["stratum"],
        "actions": actions,
        "state_before_hash": digest(state),
        "state_after_hash": digest(next_state),
    }, next_state
