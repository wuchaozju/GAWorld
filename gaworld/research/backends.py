"""Run a protocol on the engines GAWorld already has.

Nothing here simulates anything. A protocol condition *is* a parallel
world, so a protocol maps onto :class:`~gaworld.parallel.spec.ExperimentSpec`
field for field, and every seed in its validity block is one ordinary
parallel worlds experiment — written under ``output/parallel_worlds/`` like
any other, so the 平行世界 panel opens it, draws its divergence chart and
replays its worlds without knowing a study asked for it.

The seed runner is injected. The dashboard delegate hands in the real one
(``prepare_experiment`` + ``ExperimentRunner``); tests hand in a function
that returns a canned report; neither has to know about the other. Same
reason ``workbench.analyze`` takes ``llm_fn``.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from gaworld.logging_setup import get_logger
from gaworld.parallel import runner as prunner
from gaworld.parallel.spec import ExperimentSpec, normalize_experiment
from gaworld.research import survey as survey_mod
from gaworld.research.protocol import Protocol

_LOG = get_logger("gaworld.research.backends")

#: ``(progress 0..1, message)``
ReportFn = Callable[[float, str], None]
#: ``(spec, seed, report) -> {"root", "id", "status", "world_status", "report"}``
SeedRunner = Callable[[ExperimentSpec, int, ReportFn], dict[str, Any]]
#: ``(protocol, seed run, report) -> {world_id: {"scores": {measure: {...}}, ...}}``
SurveyRunner = Callable[[Protocol, dict[str, Any], ReportFn], dict[str, Any]]

#: Of each seed's slice of the progress bar, how much the survey takes.
_SURVEY_SHARE = 0.2


def experiment_payload(protocol: Protocol, seed: int, *, name: str = "") -> dict[str, Any]:
    """The dict :func:`normalize_experiment` accepts, for one seed."""
    return {
        "name": name or protocol.title,
        "note": f"seed {seed} · {protocol.kind}",
        "sim_days": protocol.sim_days,
        "agent_ids": list(protocol.sample.get("agent_ids") or []),
        "seed": seed,
        "llm_provider": protocol.sim_provider or None,
        "fast": protocol.fast,
        "max_parallel": protocol.max_parallel,
        "baseline_id": protocol.baseline_id,
        "worlds": [
            {
                "id": cond["id"],
                "label": cond["label"],
                "events": [dict(event) for event in cond.get("events") or []],
                "config": dict(cond.get("config") or {}),
                "note": cond.get("role", ""),
                "role": cond.get("role", ""),
            }
            for cond in protocol.conditions
        ],
    }


def experiment_spec(protocol: Protocol, seed: int, *, name: str = "") -> ExperimentSpec:
    """Validated through the parallel engine's own normaliser, so a study can
    never ask for a world the panel could not have built by hand."""
    return normalize_experiment(experiment_payload(protocol, seed, name=name))


def run_protocol(
    protocol: Protocol,
    *,
    run_seed: SeedRunner,
    run_survey: SurveyRunner | None = None,
    report: ReportFn | None = None,
    stop: threading.Event | None = None,
    pause: threading.Event | None = None,
    name: str = "",
) -> list[dict[str, Any]]:
    """One parallel worlds experiment per seed, sequentially.

    Sequential on purpose: a seed is already ``max_parallel`` simulations,
    and a study that ran its seeds side by side would oversubscribe the
    machine and the provider exactly the way the parallel panel refuses to.

    *pause* set holds the loop between seeds; the seed in flight is held by
    the runner itself (see :meth:`ExperimentRunner.pause`). Stopping wins, so
    a paused study can always be stopped.
    """
    seeds = protocol.seeds or [42]
    runs: list[dict[str, Any]] = []
    share = 1.0 / len(seeds)
    surveyed = protocol.kind == "composite" and run_survey is not None
    sim_share = share * (1.0 - _SURVEY_SHARE) if surveyed else share
    for index, seed in enumerate(seeds):
        _wait_while_paused(pause, stop, report, index * share)
        if stop is not None and stop.is_set():
            break
        spec = experiment_spec(protocol, seed, name=name)
        result = run_seed(spec, seed, _seed_reporter(report, seed, index * share, sim_share))
        run = {"seed": seed, **(result or {})}
        if surveyed and not (stop is not None and stop.is_set()):
            sub = _seed_reporter(report, seed, index * share + sim_share, share - sim_share)
            try:
                run["survey"] = run_survey(protocol, run, sub)
            except Exception as exc:  # one seed's survey failing is a quality issue, not a crash
                _LOG.warning("survey for seed %s failed: %s", seed, exc)
                run["survey"] = {"error": str(exc)}
        runs.append(run)
    return runs


def _wait_while_paused(
    pause: threading.Event | None,
    stop: threading.Event | None,
    report: ReportFn | None,
    progress: float,
) -> None:
    said = False
    while pause is not None and pause.is_set() and not (stop is not None and stop.is_set()):
        if report is not None and not said:
            report(progress, "已暂停，等待继续…")
            said = True
        time.sleep(0.5)


def _seed_reporter(report: ReportFn | None, seed: int, base: float, share: float) -> ReportFn:
    """Map one seed's 0..1 progress onto its slice of the whole study's."""

    def sub_report(progress: float, message: str) -> None:
        if report is not None:
            report(min(1.0, base + max(0.0, min(1.0, progress)) * share), f"种子 {seed}：{message}")

    return sub_report


def slim_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the study record keeps: everything but the report body.

    The report is megabytes of trajectories and lives in the experiment's
    own ``report.json``; the study points at it and re-reads it when asked.
    """
    return [{key: value for key, value in run.items() if key != "report"} for run in runs]


def load_report(repo_root: str, root_rel: str) -> dict[str, Any] | None:
    path = os.path.join(repo_root, root_rel, "report.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def default_seed_runner(
    *,
    repo_root: str,
    base_config: dict[str, Any] | None,
    experiment_prefix: str,
    active: dict[str, Any],
) -> SeedRunner:
    """The real thing: fork the worlds as subprocesses and wait for them.

    ``active["runner"]`` holds the live :class:`ExperimentRunner` while a
    seed runs so the delegate's *stop* and *pause* endpoints can reach it.
    """

    def run(spec: ExperimentSpec, seed: int, report: ReportFn) -> dict[str, Any]:
        manifest = prunner.prepare_experiment(
            spec,
            repo_root,
            base_config=base_config,
            experiment_id=f"{experiment_prefix}_s{seed}",
            group=experiment_prefix,
        )
        runner = prunner.ExperimentRunner(manifest, repo_root, max_parallel=spec.max_parallel)
        active["runner"] = runner
        # A pause that landed between two seeds applies to this one too.
        pause = active.get("pause")
        if pause is not None and pause.is_set():
            runner.pause()
        try:
            result = runner.run(report)
        finally:
            active["runner"] = None
        return {
            "root": manifest["root"],
            "id": manifest["id"],
            "status": runner.manifest.get("status", "unknown"),
            "world_status": dict(runner.manifest.get("world_status") or {}),
            "report": result,
        }

    return run


def _respondent_ids(repo_root: str, world: dict[str, Any], spec_ids: list[int]) -> list[int]:
    """Who lived in this world: the sample if fixed, else whoever its state
    history recorded. Household members promoted to residents
    (``family.members_as_agents``) have no profile to interview from yet and
    are left out."""
    from gaworld.family.promote import PROMOTED_ID_BASE

    if spec_ids:
        return [aid for aid in spec_ids if aid < PROMOTED_ID_BASE]
    path = os.path.join(repo_root, world.get("state_csv") or "")
    ids: list[int] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    aid = int(row.get("agent_id") or row.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if 0 < aid < PROMOTED_ID_BASE and aid not in ids:
                    ids.append(aid)
    except OSError:
        return []
    return ids


def default_survey_runner(*, repo_root: str, provider: str = "", timeout: float = 3600.0) -> SurveyRunner:
    """Interview every world's residents with that world's memories.

    One ``python -m gaworld.interview`` child per world, with the world's own
    config overrides — the same isolation the world ran under, so the memory
    store, the vector DB and the goals all resolve to that world's files —
    and the world's end-of-run state as the residents' state. Transcripts and
    scores are written to ``<world>/survey.json``.
    """

    def run(protocol: Protocol, seed_run: dict[str, Any], report: ReportFn) -> dict[str, Any]:
        manifest = prunner.load_manifest(repo_root, seed_run.get("root") or "") or {}
        worlds = manifest.get("worlds") or {}
        spec_ids = [int(a) for a in (manifest.get("spec") or {}).get("agent_ids") or []]
        survey = protocol.survey or {}
        out: dict[str, Any] = {}
        conditions = [cond for cond in protocol.conditions if cond["id"] in worlds]
        for index, cond in enumerate(conditions):
            world = worlds[cond["id"]]
            report(index / max(1, len(conditions)), f"采访世界 {cond['label']} 的居民…")
            ids = _respondent_ids(repo_root, world, spec_ids)
            if not ids:
                out[cond["id"]] = {"error": "这个世界没有可采访的居民（没有状态数据）"}
                continue
            world_dir = os.path.join(repo_root, world["dir"])
            spec_path = os.path.join(world_dir, "survey_spec.json")
            out_path = os.path.join(world_dir, "survey_answers.json")
            payload = {
                "title": f"{protocol.title} · {cond['label']}",
                "context": survey.get("context", ""),
                "provider": provider,
                "questions": survey_mod.interview_questions(survey),
                "respondents": [{"kind": "agent", "ref": str(aid), "label": f"#{aid}"} for aid in ids],
                "final_state_csv": os.path.join(world_dir, "state", "agent_state_history.csv"),
            }
            with open(spec_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            env = os.environ.copy()
            env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(world.get("overrides") or {}, ensure_ascii=False)
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.run(
                [sys.executable, "-m", "gaworld.interview", "--spec", spec_path, "--out", out_path],
                cwd=repo_root, env=env, capture_output=True, text=True, timeout=timeout,
            )
            if proc.returncode != 0 or not os.path.exists(out_path):
                tail = (proc.stderr or proc.stdout or "")[-600:]
                out[cond["id"]] = {"error": f"采访进程失败（退出码 {proc.returncode}）：{tail}"}
                continue
            with open(out_path, encoding="utf-8") as handle:
                transcripts = (json.load(handle) or {}).get("transcripts") or []
            scores = survey_mod.score(survey, transcripts)
            record = {"scores": scores, "respondents": len(ids), "transcripts": os.path.relpath(out_path, repo_root)}
            with open(os.path.join(world_dir, "survey.json"), "w", encoding="utf-8") as handle:
                json.dump({**record, "transcripts": transcripts}, handle, ensure_ascii=False)
            out[cond["id"]] = record
        report(1.0, "采访完成")
        return out

    return run


__all__ = [
    "ReportFn",
    "SeedRunner",
    "SurveyRunner",
    "default_seed_runner",
    "default_survey_runner",
    "experiment_payload",
    "experiment_spec",
    "load_report",
    "run_protocol",
    "slim_runs",
]
