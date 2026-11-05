"""Run isolated paired cells, checkpointing completed requests and failed attempts.

A cell that could not be measured — it ran out of its declared budget, the
judge never returned a usable score, or the provider refused the request —
is recorded as unmeasured. It is never scored as a wrong answer, because a
misconfigured run is not evidence that an organization is worse.
"""

from __future__ import annotations

import contextvars
import random
import threading
import time

from gaworld.collaboration import organization_engine
from gaworld.collaboration.organization_methods import digest
from gaworld.llm.failures import describe
from gaworld.research.organization_intelligence.comparison import (
    analysis,
    benchmarks,
    execution,
    protocol,
)


class Paused(Exception):
    """User-requested pause between requests."""


class Aborted(Exception):
    """Another lane stopped the run."""


class InvalidScore(ValueError):
    """The judge response was received but cannot be used as a score."""


class ScoringLimit(ValueError):
    """No further judge requests are allowed under the frozen protocol."""


class RateLimited(Exception):
    """The provider refused the request; the study waits for the user."""

    def __init__(self, message, cause=None):
        super().__init__(message)
        self.cause = cause


#: Why a cell carries no score.
REASONS = {
    "budget_exceeded": "超出本次设置的资源上限，未能测量",
    "scoring_unavailable": "评审没有给出可用分数，未能测量",
    "request_failed": "模型服务没有完成本次请求，未能测量",
    "protocol_drift": "已保存的回答与当前提示词不一致，未能测量",
}


def run(db, identifier, llm):
    from gaworld.research.organization_intelligence.comparison.protocol import runtime_fingerprint

    record = db.get(identifier)
    spec = record["protocol"]
    if record["status"] == "completed":
        return
    if digest(spec) != record["protocol_hash"] or spec.get("runtime_fingerprint") != runtime_fingerprint():
        raise ValueError("实验设置或执行器版本发生变化，不能恢复")
    db.update(
        identifier,
        lambda r: r.update(status="running", error="", error_info=None, retry_blocked_reason=""),
    )
    db.touch(identifier, control="", waiting=None)
    # Every arm runs its own method and draws its own seed. The arms of a
    # protocol frozen before the arms existed are derived, so their cells
    # and their seeds stay the ones they were.
    arms = protocol.arms_of(spec)
    arm_by_id = {arm["id"]: arm for arm in arms}

    policy = spec.get("execution_policy", {})
    interval = int(policy.get("min_interval_seconds", 0))
    lanes = max(1, int(policy.get("concurrency", 1)))
    retries = max(0, int(policy.get("automatic_retries", 0)))
    backoff = max(0, int(policy.get("retry_backoff_seconds", 2)))
    stop = threading.Event()
    lock = threading.Lock()
    failures: list[Exception] = []
    drift: list[Exception] = []

    def check():
        if db.live(identifier).get("control"):
            raise Paused()
        if stop.is_set():
            raise Aborted()

    def request_slot(lane):
        execution.wait_for_request(db, identifier, interval, check, lane=lane)

    def run_cell(qi, repeat, arm_id, lane):
        arm = arm_by_id[arm_id]
        task = spec["benchmark"]["tasks"][qi]
        key = f"{qi}:{repeat}:{arm_id}"
        record = db.get(identifier)
        if any(row["cell"] == key for row in record["rows"]):
            return
        state = db.load_state(identifier, key)
        # Each arm draws its own graph: the same seed on two arms would hand
        # a random baseline the candidate's exact communication structure.
        arm_seed = spec["seed"] + qi * 17 + repeat + arm["seed_offset"]

        def checkpoint(updated, event, cell=key):
            db.save_state(identifier, cell, updated)
            db.set_state(
                identifier,
                cell,
                {"metrics": organization_engine.execution_metrics(updated, include_scoring=True)},
            )
            db.append_event(
                identifier,
                {
                    "at": execution.now(),
                    "cell": cell,
                    "phase": event.get("phase") if isinstance(event, dict) else None,
                    "status": event.get("status") if isinstance(event, dict) else None,
                    "prompt_hash": event.get("prompt_hash") if isinstance(event, dict) else None,
                    "input_chars": event.get("input_chars") if isinstance(event, dict) else None,
                    "output_chars": event.get("output_chars") if isinstance(event, dict) else None,
                    "error": event.get("error") if isinstance(event, dict) else None,
                },
            )

        def judge(prompt, scoring, outcome):
            """Ask the judge, within the frozen number of attempts.

            An answer the judge cannot read is not a wrong answer: the attempt
            is recorded, and the cell tries again until the frozen limit is
            reached. Only then is the cell left unmeasured.
            """
            check()
            while True:
                for attempt in scoring:
                    if attempt["status"] != "completed":
                        continue
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
                        break
                    return attempt["response"]
                if len(scoring) >= spec["scoring_attempts_per_cell"]:
                    raise ScoringLimit("本题评审请求已达到固定上限")
                request_slot(lane)
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
                except Exception as exc:
                    attempt.update(
                        status="failed",
                        error=type(exc).__name__,
                        error_info=describe(exc),
                        elapsed=time.monotonic() - started,
                    )
                    checkpoint(state, attempt)
                    raise
                try:
                    benchmarks.score(task, outcome["answer"], judge=lambda _, answer=raw: answer)
                except (ValueError, TypeError, AttributeError):
                    attempt.update(
                        status="failed",
                        error="InvalidScore",
                        elapsed=time.monotonic() - started,
                    )
                    checkpoint(state, attempt)
                    continue
                attempt.update(
                    status="completed",
                    response=raw,
                    output_chars=len(raw),
                    elapsed=time.monotonic() - started,
                )
                checkpoint(state, attempt)
                return raw

        def attempt_cell():
            outcome = organization_engine.run_method(
                arm["method"],
                spec["members"],
                benchmarks.public_task(task, len(spec["members"])),
                llm,
                seed=arm_seed,
                limits=spec["limits"],
                state=state,
                checkpoint=checkpoint,
                before_call=check,
                before_request=lambda: request_slot(lane),
            )
            scoring = state.setdefault("scoring_attempts", [])
            scored = benchmarks.score(
                task,
                outcome["answer"],
                judge=lambda prompt: judge(prompt, scoring, outcome),
            )
            outcome["metrics"] = organization_engine.execution_metrics(state, include_scoring=True)
            outcome["metrics"]["scoring_calls"] = len(scoring)
            checkpoint(state, {})
            return outcome, scored, ""

        error = ""
        reason = ""
        measured = True
        outcome = {"answer": {}, "edges": [], "metrics": {}}
        scored = {}
        transport_failures = 0
        while True:
            try:
                outcome, scored, error = attempt_cell()
                break
            except organization_engine.BudgetExceeded as exc:
                measured, reason, error = False, "budget_exceeded", str(exc)
                outcome["metrics"] = organization_engine.execution_metrics(state, include_scoring=True)
                break
            except organization_engine.ProtocolDrift as exc:
                measured, reason, error = False, "protocol_drift", str(exc)
                outcome["metrics"] = organization_engine.execution_metrics(state, include_scoring=True)
                drift.append(exc)
                break
            except (InvalidScore, ScoringLimit) as exc:
                measured, reason, error = False, "scoring_unavailable", str(exc)
                outcome["metrics"] = organization_engine.execution_metrics(state, include_scoring=True)
                break
            except (Paused, Aborted, RateLimited):
                raise
            except Exception as exc:
                info = describe(exc, now=execution.now())
                if info.get("http_status") == 429:
                    raise RateLimited(str(exc), exc) from exc
                transport_failures += 1
                if transport_failures <= retries:
                    # Try once more; the saved state keeps the answers already
                    # received, so the retry resumes instead of repeating.
                    time.sleep(min(backoff * transport_failures, 30))
                    continue
                measured, reason, error = False, "request_failed", info["message"]
                outcome["metrics"] = organization_engine.execution_metrics(state, include_scoring=True)
                break
        row = {
            "cell": key,
            "task_id": task["id"],
            "category": task["category"],
            "repeat": repeat,
            "arm": arm_id,
            "measured": measured,
            "invalid_reason": reason,
            "score": scored.get("score") if measured else None,
            "valid": bool(scored.get("valid")) if measured else False,
            "answer": outcome["answer"],
            "metrics": outcome["metrics"],
            "edges": outcome["edges"],
            "error": error,
        }
        db.update(identifier, lambda r, row=row: r["rows"].append(row))

    def worker(lane):
        while not stop.is_set():
            with lock:
                if not queue:
                    return
                qi, repeat, arm = queue.pop(0)
            try:
                run_cell(qi, repeat, arm, lane)
            except Aborted:
                return
            except Exception as exc:  # recorded and reported by the caller
                with lock:
                    failures.append(exc)
                stop.set()
                return

    queue: list[tuple[int, int, str]] = []
    order = [arm["id"] for arm in arms]
    for qi in range(len(spec["benchmark"]["tasks"])):
        for repeat in range(spec["repeats"]):
            # The arms of one question may run in any order; the question and
            # the repeat they belong to never change.
            shuffled = list(order)
            random.Random(spec["seed"] + qi * 17 + repeat).shuffle(shuffled)
            for arm in shuffled:
                queue.append((qi, repeat, arm))

    try:
        # A thread starts with an empty context; without a copy the lanes
        # would forget which user and world the study belongs to.
        threads = [
            threading.Thread(target=contextvars.copy_context().run, args=(worker, lane), daemon=True)
            for lane in range(lanes)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if failures:
            raise failures[0]
        if drift:
            raise drift[0]
        db.update(identifier, lambda r: r.update(status="completed"))
    except Paused:
        control = db.live(identifier).get("control")
        db.update(identifier, lambda r: r.update(status="stopped" if control == "stop" else "paused"))
    except RateLimited as exc:
        info = describe(exc.cause or exc, now=execution.now())
        db.update(
            identifier,
            lambda r: r.update(status="rate_limited", error=info["message"], error_info=info),
        )
    except Exception as exc:
        info = describe(exc, now=execution.now())
        if isinstance(exc, (InvalidScore, ScoringLimit)):
            info["message"] = str(exc)
        status = "rate_limited" if info["http_status"] == 429 else "interrupted"
        db.update(
            identifier,
            lambda r: r.update(
                status=status,
                error=info["message"],
                error_info=info,
                retry_blocked_reason="",
            ),
        )
    finally:
        db.update(
            identifier,
            lambda r: r.update(
                analysis=analysis.analyze(
                    r["rows"],
                    expected=spec["expected"],
                    delta=spec["delta"],
                    seed=spec["seed"],
                    arms=[arm["id"] for arm in protocol.arms_of(spec)],
                )
            ),
        )
        db.touch(identifier, waiting=None)
