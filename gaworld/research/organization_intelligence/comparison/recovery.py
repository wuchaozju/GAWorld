"""Explicit linked recovery: verify replay without requests and keep source immutable."""

from __future__ import annotations

import copy
import fcntl

from gaworld.collaboration import organization_engine
from gaworld.collaboration.organization_methods import digest
from gaworld.research.organization_intelligence.comparison import analysis, benchmarks, protocol
from gaworld.research.organization_intelligence.comparison.execution import POLICY

# A recovery is allowed when the replay reproduces every saved prompt and
# score; see ``_prepare_locked``. No list of allowed code versions is kept,
# because a hash of a file on disk says less than the replay does.


class PendingResponse(Exception):
    """Replay reached a request not present in the source checkpoint."""


def prepare(db, source):
    identifier = source["id"]
    with (db.directory(identifier) / "runner.lock").open("a") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("实验仍在运行，请先暂停") from None
        return _prepare_locked(db, db.merged(identifier))


def _prepare_locked(db, source):
    spec = source["protocol"]
    if source["status"] == "draft" and source.get("recovery"):
        # An unstarted recovery has no new work: recheck its original evidence,
        # never whitelist an otherwise unknown intermediate execution version.
        parent = db.get(source["recovery"]["source_id"])
        metadata = source["recovery"]

        def comparable(p):
            return {k: v for k, v in p.items() if k not in {"runtime_fingerprint", "execution_policy"}}

        if (
            parent["id"] == source["id"]
            or parent.get("recovery")
            or metadata["source_protocol_hash"] != parent["protocol_hash"]
            or digest(spec) != source["protocol_hash"]
            or comparable(spec) != comparable(parent["protocol"])
            or source["rows"] != parent["rows"]
            or source["states"] != parent["states"]
        ):
            raise ValueError("原实验或恢复副本已变化，请打开原实验核对进度")
        for cell in source["states"]:
            if digest(db.load_state(source["id"], cell)) != metadata["evidence_hashes"].get(cell):
                raise ValueError("恢复副本的调用证据发生变化，请打开原实验")
            if digest(db.load_state(parent["id"], cell)) != metadata["evidence_hashes"].get(cell):
                raise ValueError("原实验已有新进度，请直接打开原实验继续")
        return prepare(db, parent)
    if source["status"] not in {"draft", "paused", "interrupted", "rate_limited"}:
        raise ValueError("只能恢复暂停或中断的实验")
    if source["status"] == "draft" and (source["rows"] or source["states"]):
        raise ValueError("未启动的实验存在未知进度，不能恢复")
    if digest(spec) != source["protocol_hash"]:
        raise ValueError("原实验设置校验失败")
    # No whitelist of allowed code versions: the replay below checks every
    # saved prompt against what the current engine would send, which is a
    # stronger statement than a hash of a file on disk.
    arms = protocol.arms_of(spec)
    cells = {
        f"{qi}:{repeat}:{arm['id']}": (task, repeat, arm)
        for qi, task in enumerate(spec["benchmark"]["tasks"])
        for repeat in range(spec["repeats"])
        for arm in arms
    }
    rows = {r["cell"]: r for r in source["rows"]}
    if len(rows) != len(source["rows"]) or set(rows) - set(cells):
        raise ValueError("原实验包含重复或不属于设置的结果")
    if set(source["states"]) - set(cells) or set(rows) - set(source["states"]):
        raise ValueError("原实验结果缺少对应的调用证据")
    for cell, row in rows.items():
        task, repeat, arm = cells[cell]
        if row["task_id"] != task["id"] or row["repeat"] != repeat or row["arm"] != arm["id"]:
            raise ValueError("原实验单元与成绩标记不一致")
    copied, hashes, verified = {}, {}, 0

    def no_call(*args, **kwargs):
        raise PendingResponse()

    for cell in source["states"]:
        task, repeat, arm = cells[cell]
        qi = int(cell.split(":")[0])
        state = db.load_state(source["id"], cell)
        if not isinstance(state.get("calls"), list) or not isinstance(state.get("attempts"), list):
            raise ValueError("原实验的调用证据不完整")
        completed = [a for a in state["attempts"] if a.get("status") == "completed"]
        if state["calls"] != completed:
            raise ValueError("已完成回答与请求尝试记录不一致")
        if any(
            not isinstance(a.get("prompt"), str)
            or not isinstance(a.get("response"), str)
            or digest(a["prompt"]) != a.get("prompt_hash")
            for a in completed
        ):
            raise ValueError("原调用内容与提示词指纹不一致")
        try:
            outcome = organization_engine.run_method(
                arm["method"],
                spec["members"],
                benchmarks.public_task(task, len(spec["members"])),
                no_call,
                seed=spec["seed"] + qi * 17 + repeat + arm["seed_offset"],
                limits=spec["limits"],
                state=copy.deepcopy(state),
            )
        except PendingResponse:
            if cell in rows:
                raise ValueError("已有成绩缺少完整的模型回答") from None
        except organization_engine.BudgetExceeded:
            if cell in rows and rows[cell].get("measured", True):
                raise ValueError("预算失败与原成绩不一致") from None
        else:
            if cell in rows and rows[cell].get("measured", True):

                def judge(prompt, state=state):
                    for a in state.get("scoring_attempts", []):
                        if a.get("status") == "completed" and a.get("prompt_hash") == digest(prompt):
                            return a["response"]
                    raise ValueError("原评审结果缺少完整调用证据")

                score = benchmarks.score(task, outcome["answer"], judge=judge)
                row = rows[cell]
                if (
                    row["task_id"] != task["id"]
                    or row["arm"] != arm["id"]
                    or row["repeat"] != repeat
                    or score["score"] != row["score"]
                    or score["valid"] != row["valid"]
                ):
                    raise ValueError("重放结果与原实验成绩不一致")
        copied[cell] = state
        hashes[cell] = digest(state)
        verified += len(state["calls"])
    recovered_spec = copy.deepcopy(spec)
    recovered_spec.update(runtime_fingerprint=protocol.runtime_fingerprint(), execution_policy=POLICY.copy())
    result = db.create(
        "C",
        {
            "status": "draft",
            "protocol": recovered_spec,
            "protocol_hash": digest(recovered_spec),
            "rows": copy.deepcopy(source["rows"]),
            "states": copy.deepcopy(source["states"]),
            "control": "",
            "error": "",
            "error_info": copy.deepcopy(source.get("error_info")),
            "last_request_at": source.get("last_request_at"),
            "analysis": analysis.analyze(
                source["rows"],
                expected=spec["expected"],
                delta=spec["delta"],
                seed=spec["seed"],
                arms=[arm["id"] for arm in protocol.arms_of(spec)],
            ),
            "recovery": {
                "source_id": source["id"],
                "source_protocol_hash": source["protocol_hash"],
                "source_runtime_fingerprint": spec["runtime_fingerprint"],
                "evidence_hashes": hashes,
                "verified_responses": verified,
                "reused_cells": len(source["rows"]),
                "reason": "只更新请求节奏与错误处理；原成员、题目、模型、组织方式和已有回答保持不变",
            },
        },
    )
    try:
        for cell, state in copied.items():
            db.save_state(result["id"], cell, state)
    except Exception:
        db.update(
            result["id"], lambda r: r.update(status="recovery_failed", error="恢复证据写入失败，请保留原实验")
        )
        raise
    return result
