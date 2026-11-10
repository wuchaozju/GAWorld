"""Dashboard backend for 社会调查/实验拟合度 — the research workbench's replication tab.

Reached through :mod:`gaworld.apps.research_api`, which forwards everything
under ``/api/research/replication`` here, the way it forwards the policy tab.

Reading a paper is one model call and a run is one call per resident per
condition, so both are jobs on a :class:`JobStore`. The extracted spec is the
extraction job's result (the panel shows it for checking, then sends it back
with ``/run``); a finished run is written to ``output/research/replication/``
and listed from disk.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps.game_jobs import JobStore
from gaworld.research import model_provenance as mp
from gaworld.research import replication as rp
from gaworld.research import replication_export as rex
from gaworld.research import replication_interpret as ri
from gaworld.research import result_checks as rc

_JOBS = JobStore("replication")

#: Injected by tests; ``None`` means the configured provider via ``call_llm``.
_LLM_OVERRIDE: Callable[[str, str, str], str] | None = None

PREFIX = "/api/research/replication"

#: The generation parameters of each stage, and what they default to.
#:
#: Temperature and token budget are part of the protocol, so a researcher may
#: change them; the defaults are what a run uses when nobody says otherwise.
GENERATION_DEFAULTS: dict[str, dict[str, float | int]] = {
    "extract": {"temperature": 0.1, "max_tokens": rp.EXTRACT_MAX_TOKENS},
    "answer": {"temperature": 0.9, "max_tokens": rp.ANSWER_MAX_TOKENS},
    "interpret": {"temperature": 0.3, "max_tokens": ri.INTERPRET_MAX_TOKENS},
}


def _llm(
    provider: str,
    task: str,
    temperature: float,
    max_tokens: int,
    journal: mp.CallJournal | None = None,
) -> Callable[..., str]:
    override = _LLM_OVERRIDE
    task_name = f"research.replication.{task}"
    provenance = {
        "provider": provider,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "allow_fallback": False,
        "kind": "injected" if override else "configured",
    }
    model_name = ""
    if override is None:
        from gaworld.llm import providers

        provider = providers.resolve_provider(task=task_name, provider=provider or None)
        router = providers.LLM_ROUTER
        backend = router.providers[provider]
        cfg = deepcopy(router.config.get("llm", {}).get("providers", {}).get(provider, {}))
        model = str(getattr(backend, "model", ""))
        endpoint = str(getattr(backend, "base_url", getattr(backend, "url", "")))
        model_name = model
        provenance.update(
            provider=provider,
            model=model,
            backend_type=type(backend).__name__,
            endpoint_hash=rc.fingerprint(endpoint),
            generation_settings={
                key: cfg[key]
                for key in (
                    "top_p",
                    "top_k",
                    "seed",
                    "repeat_penalty",
                    "frequency_penalty",
                    "presence_penalty",
                    "reasoning_effort",
                )
                if key in cfg
            },
        )
        provenance["config_hash"] = mp.provider_details(provider).get("config_hash", "")

    def call(prompt: str, seed: int | None = None) -> str:
        started = time.monotonic()
        try:
            if override is not None:
                # An injected model stands in for the provider; it is given the
                # seed so a test can tell two cells apart.
                text = override(prompt, task, provider)
            else:
                if (
                    providers.LLM_ROUTER is not router
                    or router.providers.get(provider) is not backend
                    or str(getattr(backend, "model", "")) != model
                    or str(getattr(backend, "base_url", getattr(backend, "url", ""))) != endpoint
                    or router.config.get("llm", {}).get("providers", {}).get(provider, {}) != cfg
                ):
                    raise RuntimeError("实验期间模型配置已改变，请固定配置后重新运行")

                kwargs: dict = {
                    "task": task_name,
                    "provider": provider,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "allow_fallback": False,
                }
                if seed is not None:
                    kwargs["seed"] = int(seed)
                text = str(providers.call_llm(prompt, **kwargs))
        except Exception as exc:
            if journal is not None:
                journal.record(
                    **mp.journal_entry(
                        task=task_name,
                        provider=provider,
                        model=model_name or "injected",
                        temperature=temperature,
                        max_tokens=max_tokens,
                        seed=seed,
                        prompt=prompt,
                        started=started,
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            raise
        if journal is not None:
            journal.record(
                **mp.journal_entry(
                    task=task_name,
                    provider=provider,
                    model=model_name or "injected",
                    temperature=temperature,
                    max_tokens=max_tokens,
                    seed=seed,
                    prompt=prompt,
                    started=started,
                    ok=True,
                    answer=text,
                )
            )
        return text

    call.provenance = provenance
    return call


def reset() -> None:
    """Drop in-memory jobs. Used by tests; production code never calls it."""
    _JOBS.reset()


def start_extract(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("先上传或粘贴一篇文献")
    title = str(payload.get("title") or "")
    provider = str(payload.get("provider") or "")
    generation = mp.normalize_generation(payload.get("generation"), GENERATION_DEFAULTS)
    stage = generation["extract"]

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(0.1, "正在阅读文献、抽取研究设计和真人结果…")
        llm = _llm(
            provider,
            "extract",
            temperature=float(stage["temperature"]),
            max_tokens=int(stage["max_tokens"]),
        )
        spec = rp.extract_spec(text, title=title, llm=llm)
        return {
            "spec": spec,
            "generation": {"extract": stage},
            "model": dict(getattr(llm, "provenance", {}) or {}),
        }

    return {"job_id": _JOBS.run(work), "truncated": len(text) > rp.MAX_PAPER_CHARS}


def _interpret(
    run: dict[str, Any],
    provider: str,
    language: str,
    generation: dict[str, dict[str, float | int]] | None = None,
    journal: mp.CallJournal | None = None,
) -> dict[str, Any]:
    """The reading, or ``{"error": ...}``: a failed reading never fails the run it reads."""
    stage = (generation or GENERATION_DEFAULTS)["interpret"]
    try:
        llm = _llm(
            provider,
            "interpret",
            temperature=float(stage["temperature"]),
            max_tokens=int(stage["max_tokens"]),
            journal=journal,
        )
        return {
            **ri.interpret(run, llm_fn=llm, language=language),
            "provider": provider,
            "generation": {"interpret": stage},
            "model": dict(getattr(llm, "provenance", {}) or {}),
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def start_interpret(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    run = rp.load_run(run_id)
    if run is None or not ownership.visible(run):
        raise KeyError(run_id)
    provider = str(payload.get("provider") or "")
    language = str(payload.get("language") or "zh-CN")
    generation = mp.normalize_generation(payload.get("generation"), GENERATION_DEFAULTS)

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(0.1, "正在解读偏差…")
        fresh = rp.load_run(run_id) or run
        journal = mp.CallJournal()
        fresh["interpretation"] = _interpret(fresh, provider, language, generation, journal)
        fresh.setdefault("generation", {})["interpret"] = generation["interpret"]
        fresh["model_calls"] = mp.link_calls(journal.entries(), fresh) + list(fresh.get("model_calls") or [])
        rp.save_run(fresh)
        return {"run_id": run_id, "error": fresh["interpretation"].get("error")}

    return {"job_id": _JOBS.run(work)}


def start_run(payload: dict[str, Any]) -> dict[str, Any]:
    spec = rp.normalize_spec(payload.get("spec"))
    if not spec["items"]:
        raise ValueError("规格里没有题目")
    if not spec["results"]:
        raise ValueError("规格里没有真人结果，无法比较")
    provider = str(payload.get("provider") or "")
    seed = payload.get("seed")
    city = str(payload.get("city") or "")
    city_name = str(payload.get("city_name") or "")
    sample_size = int(payload.get("sample_size") or rp.DEFAULT_SAMPLE)
    design = str(payload.get("design") or "between")
    interpret = bool(payload.get("interpret", True))
    language = str(payload.get("language") or "zh-CN")
    generation = mp.normalize_generation(payload.get("generation"), GENERATION_DEFAULTS)
    answer_stage = generation["answer"]

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(0.01, "正在抽样居民…")
        journal = mp.CallJournal()
        answer = _llm(
            provider,
            "answer",
            temperature=float(answer_stage["temperature"]),
            max_tokens=int(answer_stage["max_tokens"]),
            journal=journal,
        )
        run = rp.run_replication(
            spec=spec,
            city=city,
            city_name=city_name,
            sample_size=sample_size,
            seed=int(seed) if seed not in (None, "") else None,
            design=design,
            provider=provider,
            answer=answer,
            progress=progress,
        )
        run.update(ownership.stamp())
        # What was asked, and what answered: the run keeps the parameters it
        # used and one row per model call, so a reader can check the numbers
        # instead of taking them on trust.
        run["generation"] = generation
        run["model"] = dict(getattr(answer, "provenance", {}) or {})
        # Which model read the paper may differ from the one playing the
        # residents; the record says both.
        run["extraction_model"] = dict(payload.get("extraction_model") or {})
        run["model_calls"] = mp.link_calls(journal.entries(), run)
        rp.save_run(run)
        if interpret and run["failed"] < len(run["responses"]):
            progress(0.99, "正在解读偏差…")
            run["interpretation"] = _interpret(run, provider, language, generation, journal)
            run["generation"] = generation
            run["model_calls"] = mp.link_calls(journal.entries(), run)
        rp.save_run(run)
        return {"run_id": run["id"]}

    return {"job_id": _JOBS.run(work)}


def _parts(path: str) -> list[str]:
    """``/api/research/replication/a/b`` → ``["a", "b"]``."""
    return [p for p in path[len(PREFIX) :].split("/") if p]


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    parts = _parts(path)
    if not parts:
        limits = {
            "max_sample": rp.MAX_SAMPLE,
            "min_sample": rp.MIN_SAMPLE,
            "default_sample": rp.DEFAULT_SAMPLE,
        }
        return {
            "runs": ownership.owned(rp.list_runs()),
            **limits,
            # What a researcher may set before running, and which model would
            # answer: the panel shows both instead of guessing.
            "generation": GENERATION_DEFAULTS,
            "stage_labels": mp.STAGE_LABELS,
            "providers": mp.describe_providers(),
        }, 200
    if parts[0] == "jobs" and len(parts) == 2:
        record = _JOBS.status(parts[1])
        return (record, 200) if record else ({"error": "Unknown job"}, 404)
    run = rp.load_run(parts[0])
    if run is None or not ownership.visible(run):
        return {"error": "Unknown replication run"}, 404
    if len(parts) == 1:
        return run, 200
    if len(parts) == 2 and parts[1] == "export":
        return {"filename": f"{run['id']}.md", "markdown": rp.export_markdown(run)}, 200
    if len(parts) == 2 and parts[1] == "bundle":
        return {
            "filename": rex.bundle_filename(run),
            "bytes_base64": base64.b64encode(rex.export_bundle(run)).decode("ascii"),
        }, 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    parts = _parts(path)
    try:
        if parts == ["extract"]:
            return start_extract(payload), 202
        if parts == ["check"]:
            spec = rp.normalize_spec(payload.get("spec"))
            result = {
                "spec": spec,
                "coverage": rp.coverage(spec),
                "leaks": rp.leak_findings(spec),
            }
            if "city" in payload:
                from gaworld.interview.roster import recruitment_population

                people = recruitment_population(str(payload.get("city") or ""))
                result.update(eligible=len(rp.eligible_residents(people, spec)), total=len(people))
            return result, 200
        if parts == ["run"]:
            return start_run(payload), 202
        if len(parts) == 2 and parts[1] == "interpret":
            return start_interpret(parts[0], payload), 202
        if len(parts) == 2 and parts[1] == "delete":
            if not ownership.visible(rp.load_run(parts[0])):
                return {"error": "Unknown replication run"}, 404
            return {"deleted": rp.delete_run(parts[0]), "run_id": parts[0]}, 200
    except KeyError:
        return {"error": "Unknown replication run"}, 404
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}, 400
    return {"error": "Unknown endpoint"}, 404


__all__ = ["handle_get", "handle_post", "reset", "start_extract", "start_interpret", "start_run"]
