"""Run isolated paired cells, checkpointing completed requests and failed attempts."""

from __future__ import annotations

import random
import time

from gaworld.collaboration import organization_engine
from gaworld.collaboration.organization_methods import digest
from gaworld.llm.failures import describe
from gaworld.research.organization_intelligence.comparison import analysis, benchmarks, execution


class Paused(Exception):
    """User-requested pause between requests."""


class InvalidScore(ValueError):
    """The judge response was received but cannot be used as a score."""


class ScoringLimit(ValueError):
    """No further judge requests are allowed under the frozen protocol."""


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
    db.update(
        identifier,
        lambda r: r.update(
            status="running", error="", error_info=None, waiting=None, retry_blocked_reason=""
        ),
    )

    def check():
        if db.get(identifier).get("control"):
            raise Paused()

    def request_slot():
        execution.wait_for_request(
            db, identifier, spec.get("execution_policy", {}).get("min_interval_seconds", 0), check
        )

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
                            before_request=request_slot,
                        )
                        scoring = state.setdefault("scoring_attempts", [])

                        def judge(
                            prompt,
                            scoring=scoring,
                            state=state,
                            checkpoint=checkpoint,
                            task=task,
                            outcome=outcome,
                        ):
                            check()
                            for attempt in scoring:
                                if attempt["status"] == "completed":
                                    if attempt["prompt_hash"] != digest(prompt):
                                        raise ValueError("评审输入与保存记录不同")
                                    try:
                                        benchmarks.score(
                                            task,
                                            outcome["answer"],
                                            judge=lambda _, response=attempt["response"]: response,
                                        )
                                    except (ValueError, TypeError, AttributeError):
                                        attempt.update(status="failed", error="InvalidScore")
                                        checkpoint(state, attempt)
                                        continue
                                    return attempt["response"]
                            if len(scoring) >= spec["scoring_attempts_per_cell"]:
                                raise ScoringLimit("本题评审请求已达到固定上限，请另建实验")
                            request_slot()
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
                                attempt.update(response=raw, output_chars=len(raw))
                                try:
                                    benchmarks.score(task, outcome["answer"], judge=lambda _: raw)
                                except (ValueError, TypeError, AttributeError):
                                    raise InvalidScore("评审没有返回合法分数，请点击重新运行") from None
                            except Exception as exc:
                                attempt.update(
                                    status="failed",
                                    error=type(exc).__name__,
                                    error_info=describe(exc),
                                    elapsed=time.monotonic() - started,
                                )
                                checkpoint(state, attempt)
                                if (
                                    isinstance(exc, InvalidScore)
                                    and len(scoring) >= spec["scoring_attempts_per_cell"]
                                ):
                                    raise ScoringLimit("评审响应无效且请求已达固定上限，请另建实验") from None
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
        info = describe(exc, now=execution.now())
        if isinstance(exc, (InvalidScore, ScoringLimit)):
            info["message"] = str(exc)
        status = "rate_limited" if info["http_status"] == 429 else "interrupted"
        db.update(
            identifier,
            lambda r, blocked=str(exc) if isinstance(exc, ScoringLimit) else "": r.update(
                status=status,
                error=info["message"],
                error_info=info,
                waiting=None,
                retry_blocked_reason=blocked,
            ),
        )
    finally:
        db.update(
            identifier,
            lambda r: r.update(
                analysis=analysis.analyze(
                    r["rows"], expected=spec["expected"], delta=spec["delta"], seed=spec["seed"]
                )
            ),
        )
