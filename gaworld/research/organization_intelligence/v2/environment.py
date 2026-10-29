"""Truth lives here; policy receives only role views and explicitly paid checks."""

import copy
import random

from .protocol import digest


def make_task(seed, phase, index):
    rng = random.Random(f"OI2:{seed}:{phase}:{index}")
    reliability = [0.9, 0.5, 0.1]
    random.Random(f"sources:{seed}").shuffle(reliability)
    truth = [[rng.randint(0, 10) for _ in range(4)] for _ in range(3)]
    if index % 2:
        truth[index % 3] = [v * 2 for v in truth[index % 3]]
    local = [[max(0, v + rng.choice([-3, -1, 0, 0, 0, 1, 3])) for v in row] for row in truth]
    source = index % 3
    reliable = rng.random() < reliability[source]
    common = copy.deepcopy(truth) if reliable else [[max(row) - v for v in row] for row in truth]
    identifier = f"{seed}:{phase}:{index}"
    return {
        "id": identifier,
        "truth": truth,
        "local": local,
        "common": common,
        "source": f"external-{source}",
        "check_cost": 0.3 if index % 2 == 0 else 4.0,
        "stratum": f"{'cheap' if index % 2 == 0 else 'costly'}-{'reliable' if reliable else 'misleading'}",
        "input_hash": digest([identifier, truth, local, common]),
    }


def views(task):
    return [
        {
            "role": role,
            "local": {"id": f"{task['id']}:local:{role}", "values": list(task["local"][role])},
            "common": {"id": f"{task['id']}:common", "values": copy.deepcopy(task["common"])},
            "source": task["source"],
            "check_cost": task["check_cost"],
            "task_id": task["id"],
        }
        for role in range(3)
    ]


def verify(task, role, checks_used):
    if type(role) is not int or role not in range(3) or checks_used >= 2:
        raise ValueError("核验权限或预算无效")
    return list(task["truth"][role])


def feedback(task, choice):
    """Training public outcome: selected option only, never the unchosen alternatives."""
    return [row[choice] for row in task["truth"]]


def score(task, choice):
    if type(choice) is not int or choice not in range(4):
        raise ValueError("候选方案无效")
    utilities = [sum(row[i] for row in task["truth"]) for i in range(4)]
    return {"reward": utilities[choice], "oracle_reward": max(utilities)}
