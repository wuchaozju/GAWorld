"""Run isolated paired cells, checkpointing completed requests and failed attempts."""

from __future__ import annotations

import random
import time

from gaworld.collaboration import organization_engine
from gaworld.collaboration.organization_methods import digest
from gaworld.research.organization_intelligence.comparison import analysis, benchmarks


class Paused(Exception):
    """User-requested pause between requests."""


def run(db, identifier, llm):
    from gaworld.research.organization_intelligence.comparison.protocol import runtime_fingerprint

    record = db.get(identifier)
    spec = record["protocol"]
    if record["status"] == "completed":
        return
    if (
        digest(spec) != record["protocol_hash"]
        or spec["engine_version"] != organization_engine.VERSION
        or spec.get("runtime_fingerprint") != runtime_fingerprint()
    ):
        raise ValueError("实验设置或执行器版本发生变化，不能恢复")
    db.update(identifier, lambda r: r.update(status="running", error=""))

    def check():
        if db.get(identifier).get("control"):
            raise Paused()

    try:
        for qi, task in enumerate(spec["benchmark"]["tasks"]):
            for repeat in range(spec["repeats"]):
                order = ["candidate", "baseline"]
                random.Random(spec["seed"] + qi * 17 + repeat).shuffle(order)
                for arm in order:
                    check()
                    key = f"{qi}:{repeat}:{arm}"
                    record = db.get(identifier)
                    if any(row["cell"] == key for row in record["rows"]):
                        continue
                    state = db.load_state(identifier, key)

                    def checkpoint(updated, event, cell=key):
                        db.save_state(identifier, cell, updated)
                        summary = {
                            "metrics": organization_engine.execution_metrics(updated, include_scoring=True)
                        }
                        db.update(identifier, lambda r: r["states"].update({cell: summary}))

                    try:
                        outcome = organization_engine.run_method(
                            spec[arm],
                            spec["members"],
                            benchmarks.public_task(task, len(spec["members"])),
                            llm,
                            seed=spec["seed"] + qi * 17 + repeat,
                            limits=spec["limits"],
                            state=state,
                            checkpoint=checkpoint,
                            before_call=check,
                        )
                        scoring = state.setdefault("scoring_attempts", [])

                        def judge(prompt, scoring=scoring, state=state, checkpoint=checkpoint):
                            check()
                            for attempt in scoring:
                                if attempt["status"] == "completed":
                                    if attempt["prompt_hash"] != digest(prompt):
                                        raise ValueError("评审输入与保存记录不同")
                                    return attempt["response"]
                            if len(scoring) >= spec["scoring_attempts_per_cell"]:
                                raise ValueError("本题评审请求已达到固定上限")
                            attempt = {
                                "status": "started",
                                "prompt_hash": digest(prompt),
                                "prompt": prompt,
                                "input_chars": len(prompt),
                                "output_chars": 0,
                                "elapsed": 0,
                            }
                            scoring.append(attempt)
                            checkpoint(state, attempt)
                            started = time.monotonic()
                            try:
                                raw = llm(prompt, agent_id=None)
                            except Exception as exc:
                                attempt.update(
                                    status="failed",
                                    error=type(exc).__name__,
                                    elapsed=time.monotonic() - started,
                                )
                                checkpoint(state, attempt)
                                raise
                            attempt.update(
                                status="completed",
                                response=raw,
                                output_chars=len(raw),
                                elapsed=time.monotonic() - started,
                            )
                            checkpoint(state, attempt)
                            return raw

                        scored = benchmarks.score(task, outcome["answer"], judge=judge)
                        outcome["metrics"] = organization_engine.execution_metrics(
                            state, include_scoring=True
                        )
                        outcome["metrics"]["scoring_calls"] = len(scoring)
                        checkpoint(state, {})
                        error = ""
                    except organization_engine.BudgetExceeded as exc:
                        outcome = {
                            "answer": {},
                            "edges": [],
                            "metrics": organization_engine.execution_metrics(state, include_scoring=True),
                        }
                        scored, error = {"score": 0, "valid": False}, str(exc)
                    row = {
                        "cell": key,
                        "task_id": task["id"],
                        "category": task["category"],
                        "repeat": repeat,
                        "arm": arm,
                        **scored,
                        "answer": outcome["answer"],
                        "metrics": outcome["metrics"],
                        "edges": outcome["edges"],
                        "error": error,
                    }
                    db.update(identifier, lambda r, row=row: r["rows"].append(row))
        db.update(identifier, lambda r: r.update(status="completed"))
    except Paused:
        db.update(identifier, lambda r: r.update(status="stopped" if r["control"] == "stop" else "paused"))
    except Exception as exc:
        error = type(exc).__name__
        db.update(identifier, lambda r: r.update(status="interrupted", error=error))
    finally:
        db.update(
            identifier,
            lambda r: r.update(
                analysis=analysis.analyze(
                    r["rows"], expected=spec["expected"], delta=spec["delta"], seed=spec["seed"]
                )
            ),
        )
