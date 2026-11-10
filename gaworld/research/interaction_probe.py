"""Isolated synchronous rounds; each arm reads only its own previous snapshot."""

from __future__ import annotations

import contextvars
import copy
import json
import random
from concurrent.futures import ThreadPoolExecutor

from gaworld.research import result_checks as rc

ARMS = ("fresh", "self", "peers", "both")


def execute(*, spec, groups, baseline, personas, answer, prompt_fn, parse_fn, seed, workers, progress):
    initial = {(r["agent_id"], r["condition"]): r for r in baseline}
    states = dict.fromkeys(ARMS, initial)
    jobs = [(member, g["condition"], g) for g in groups for member in g["members"]]
    conditions = {c["id"]: c for c in spec["conditions"]}
    context = contextvars.copy_context()
    rounds = []
    total = len(jobs) * spec["interaction_probe"]["rounds"]
    done = 0

    def visible(values):
        result = {}
        for item in spec["items"]:
            value = (values or {}).get(item["id"])
            if value is not None and item["kind"] == "choice":
                value = item["options"][int(value)]
            result[item["id"]] = value
        return result

    for number in range(1, spec["interaction_probe"]["rounds"] + 1):
        orders = {}
        for cid in conditions:
            selected = sorted(member for member, condition, _ in jobs if condition == cid)
            permutation = list(ARMS)
            rng = random.Random(f"interaction:{seed}:{cid}:{number}")
            rng.shuffle(permutation)
            rng.shuffle(selected)
            for i, member in enumerate(selected):
                offset = i % len(ARMS)
                orders[(member, cid)] = permutation[offset:] + permutation[:offset]

        def ask(job, orders=orders, states=states, number=number):
            member, cid, group = job
            row = {
                "agent_id": member,
                "condition": cid,
                "group": group["id"],
                "arm_order": orders[(member, cid)],
                "arms": {},
            }
            for arm in row["arm_order"]:
                previous = states[arm]
                own = (
                    copy.deepcopy(previous[(member, cid)].get("answers") or {})
                    if arm in ("self", "both")
                    else None
                )
                peers = (
                    [
                        {
                            "agent_id": other,
                            "answers": copy.deepcopy(previous[(other, cid)].get("answers") or {}),
                        }
                        for other in group["members"]
                        if other != member
                    ]
                    if arm in ("peers", "both")
                    else []
                )
                exposure = {"own": own, "peers": peers}
                presented = {
                    "own": visible(own) if own is not None else None,
                    "peers": [visible(p["answers"]) for p in peers],
                }
                prompt = (
                    prompt_fn(personas[member], spec, conditions[cid])
                    + "\n\n【本轮可见的过往回答】\n"
                    + json.dumps(presented, ensure_ascii=False)
                    + "\n【作答要求】\n请重新独立判断并回答原问题；空值表示没有可用回答，按原 JSON 格式输出。"
                )
                try:
                    raw = str(
                        rc.call_with_seed(answer, prompt, rc.derive_seed(seed, member, cid, number, arm))
                    )
                    parsed = parse_fn(spec, raw)
                    if not parsed["ok"]:
                        parsed["error"] = "无法解析有效回答"
                except Exception as exc:
                    raw = ""
                    parsed = {"ok": False, "answers": {}, "error": f"{type(exc).__name__}: {exc}"}
                row["arms"][arm] = {
                    **parsed,
                    "raw": raw[:12000],
                    "prompt_hash": rc.fingerprint(prompt),
                    "source_round": number - 1,
                    "exposure": exposure,
                }
            return row

        # No branch state changes until every participant has completed this round.
        with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="interaction") as executor:
            rows = list(executor.map(lambda job: context.copy().run(ask, job), jobs))
        rounds.append({"round": number, "responses": rows})
        states = {arm: {(r["agent_id"], r["condition"]): r["arms"][arm] for r in rows} for arm in ARMS}
        done += len(rows)
        progress(
            0.5 + 0.48 * done / total, f"互动对照已完成 {number}/{spec['interaction_probe']['rounds']} 轮"
        )
    return {"version": 1, "settings": spec["interaction_probe"], "groups": groups, "rounds": rounds}
