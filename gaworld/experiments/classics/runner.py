"""Run the classic paradigms on residents: one stateless call per cell.

A cell is ``(paradigm, item, condition, resident, draw)``. Every resident
gets every condition — see :mod:`.paradigms` for why that is a paired
design and not contamination. Same habits as the demand experiment's
runner: an append-only ``results.jsonl`` with the raw answer (parsing
waits for analysis, so a parser fix costs a re-parse, not a re-run),
resume by key, a lock against two writers, and a circuit breaker for a
dead backend.
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from gaworld.experiments.classics.paradigms import PARADIGMS, build_prompt
from gaworld.experiments.runner import _done_keys
from gaworld.experiments.subjects import Subject, load_subjects
from gaworld.llm.providers import call_llm, resolve_provider
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.experiments.classics")

DEFAULT_OUTPUT_DIR = Path("output/experiments/classics")


@dataclass
class ClassicSpec:
    paradigms: list[str] = field(default_factory=lambda: list(PARADIGMS))
    subject_limit: int = 40
    subject_ids: list[int] | None = None
    #: Calls per (resident, condition). Variation comes from the residents.
    draws: int = 1
    temperature: float = 1.0
    provider: str | None = None
    seed: int = 42
    max_workers: int = 8
    name: str = "default"
    output_dir: str | Path = DEFAULT_OUTPUT_DIR

    def validate(self) -> None:
        unknown = [p for p in self.paradigms if p not in PARADIGMS]
        if unknown:
            raise ValueError(f"未知范式：{unknown}。可选：{', '.join(PARADIGMS)}")
        if self.draws < 1:
            raise ValueError("draws 至少为 1")


@dataclass(frozen=True)
class Cell:
    paradigm: str
    item: str
    condition: str
    subject: Subject
    draw: int

    @property
    def key(self) -> str:
        return f"{self.paradigm}|{self.item}|{self.condition}|{self.subject.id}|{self.draw}"


def build_cells(spec: ClassicSpec) -> list[Cell]:
    spec.validate()
    subjects = load_subjects(limit=spec.subject_limit, ids=spec.subject_ids, seed=spec.seed)
    if not subjects:
        raise ValueError("没有可用的居民：检查配置里的 csv_path / md_path")
    return [
        Cell(paradigm_id, item.id, condition, subject, draw)
        for paradigm_id in spec.paradigms
        for item in PARADIGMS[paradigm_id].items
        for condition in PARADIGMS[paradigm_id].conditions
        for subject in subjects
        for draw in range(spec.draws)
    ]


def _record(spec: ClassicSpec, cell: Cell) -> dict:
    paradigm = PARADIGMS[cell.paradigm]
    item = next(i for i in paradigm.items if i.id == cell.item)
    system, user = build_prompt(paradigm, item, cell.condition, cell.subject)
    row: dict = {
        "key": cell.key,
        "paradigm": cell.paradigm,
        "item": cell.item,
        "condition": cell.condition,
        "subject_id": cell.subject.id,
        "draw": cell.draw,
        # Covariates for the heterogeneity split, so analysis needs no city files.
        "age": cell.subject.age,
        "monthly_income": cell.subject.monthly_income,
        "provider": resolve_provider(task="experiment", provider=spec.provider),
    }
    try:
        row["raw"] = call_llm(
            user,
            task="experiment",
            provider=spec.provider,
            system=system,
            temperature=spec.temperature,
            allow_fallback=False,
        )
    except Exception as exc:  # a dead cell must not kill the run
        _LOG.warning("classic cell failed key=%s error=%s", cell.key, exc)
        row["error"] = str(exc)
    return row


def plan_lines(spec: ClassicSpec, cells: list[Cell], todo: list[Cell]) -> list[str]:
    lines = [
        f"经典实验 {spec.name}：共 {len(cells)} 次调用（待跑 {len(todo)}），temperature={spec.temperature}"
    ]
    for paradigm_id in spec.paradigms:
        total = sum(1 for c in cells if c.paradigm == paradigm_id)
        pending = sum(1 for c in todo if c.paradigm == paradigm_id)
        lines.append(f"  {paradigm_id:<22} {total:>5} 次（待跑 {pending}）· {PARADIGMS[paradigm_id].name}")
    return lines


def run(spec: ClassicSpec, *, dry_run: bool = False, resume: bool = True, abort_after: int = 20) -> Path:
    """Run every cell not already in ``results.jsonl``; return its path."""
    cells = build_cells(spec)
    out_dir = Path(spec.output_dir) / spec.name
    results_path = out_dir / "results.jsonl"
    done = _done_keys(results_path) if resume else set()
    todo = [cell for cell in cells if cell.key not in done]
    print("\n".join(plan_lines(spec, cells, todo)), flush=True)
    if dry_run:
        print(f"dry-run：未发起任何调用。结果会写到 {results_path}")
        return results_path

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "spec.json").write_text(
        json.dumps(
            {
                **{k: (str(v) if isinstance(v, Path) else v) for k, v in vars(spec).items()},
                "total_cells": len(cells),
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    lock_path = out_dir / "run.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f"{lock_path} 已存在：同名实验可能正在运行；确认没有后删掉它再重试。") from None
    os.write(fd, f"{os.getpid()}\n".encode())
    os.close(fd)
    try:
        _execute(spec, todo, results_path, abort_after)
    finally:
        lock_path.unlink(missing_ok=True)
    return results_path


def _execute(spec: ClassicSpec, todo: list[Cell], results_path: Path, abort_after: int) -> None:
    lock = threading.Lock()
    completed = failed = 0
    with open(results_path, "a", encoding="utf-8") as handle, ThreadPoolExecutor(spec.max_workers) as pool:
        futures = [pool.submit(contextvars.copy_context().run, _record, spec, cell) for cell in todo]
        for future in as_completed(futures):
            row = future.result()
            with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                completed += 1
                failed += "error" in row
                if completed >= abort_after and failed == completed:
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError(
                        f"前 {completed} 次调用全部失败，已中止（最后一个错误：{str(row.get('error'))[:200]}）。"
                        "修好后端后重跑同一条命令即可续跑。"
                    )
                if completed % 50 == 0 or completed == len(todo):
                    print(f"  进度 {completed}/{len(todo)}（失败 {failed}）", flush=True)


__all__ = ["DEFAULT_OUTPUT_DIR", "Cell", "ClassicSpec", "build_cells", "plan_lines", "run"]
