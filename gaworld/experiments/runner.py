"""Grid runner for the demand-estimation prompt experiment.

One cell = one model call = ``(arm, question, product, price level,
subject, draw)``. The runner is deliberately *not* the parallel-worlds
runner: there is no day loop, no memory to isolate, no state to carry
forward. It is a wide, embarrassingly parallel sweep with a resumable
append-only log, because the full design is tens of thousands of calls
and any run long enough to matter will be interrupted at least once.

Results land in ``results.jsonl`` — one JSON object per call, raw text
included. Parsing happens at analysis time so a parser bug costs a
re-parse rather than a re-run.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from gaworld.experiments.analysis import parse_elicit, parse_purchase
from gaworld.experiments.arms import ARMS, ELICIT_FIELDS, build_prompt
from gaworld.experiments.stimulus import (
    DEFAULT_CATALOG,
    RELATIVE_PRICE_GRID,
    Treatment,
    load_catalog,
    price_grid,
)
from gaworld.experiments.subjects import Subject, load_subjects, world_context
from gaworld.llm.providers import call_llm, resolve_provider
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.experiments")

DEFAULT_OUTPUT_DIR = Path("output/experiments")


@dataclass
class RunSpec:
    """Everything that defines a run, and nothing that varies within it."""

    arms: list[str] = field(default_factory=lambda: ["blind", "unblinded", "agent"])
    questions: list[str] = field(default_factory=lambda: ["elicit", "purchase"])
    catalog: str | Path = DEFAULT_CATALOG
    groups: list[str] | None = None
    product_limit: int | None = None
    grid: tuple[float, ...] = RELATIVE_PRICE_GRID
    subject_limit: int = 20
    subject_ids: list[int] | None = None
    draws: int = 1
    #: Draws per cell for arms that have subjects. Kept separate because the
    #: two arm families get their variation from different places: a
    #: subject-less arm has only sampling noise, so it needs the paper's 50
    #: draws, while an arm with subjects already varies across people and
    #: would otherwise cost ``subjects ×`` as much for variation it has.
    subject_draws: int = 1
    temperature: float = 1.0
    provider: str | None = None
    seed: int = 42
    elicit_fields: tuple[str, ...] = ELICIT_FIELDS
    max_workers: int = 8
    name: str = "demand"
    output_dir: str | Path = DEFAULT_OUTPUT_DIR

    def validate(self) -> None:
        unknown = [arm for arm in self.arms if arm not in ARMS]
        if unknown:
            raise ValueError(f"Unknown arms: {unknown}. Known: {', '.join(sorted(ARMS))}")
        bad = [q for q in self.questions if q not in {"elicit", "purchase"}]
        if bad:
            raise ValueError(f"Unknown questions: {bad}")
        if self.draws < 1 or self.subject_draws < 1:
            raise ValueError("draws and subject_draws must be >= 1")


@dataclass(frozen=True)
class Cell:
    arm: str
    question: str
    treatment: Treatment
    subject: Subject | None
    draw: int

    @property
    def key(self) -> str:
        subject_id = self.subject.id if self.subject else "-"
        return f"{self.arm}|{self.question}|{self.treatment.id}|{subject_id}|{self.draw}"


def build_cells(spec: RunSpec) -> list[Cell]:
    """Expand the spec into the full call grid."""
    spec.validate()
    products = load_catalog(spec.catalog, groups=spec.groups, limit=spec.product_limit)
    treatments = price_grid(products, spec.grid)
    subjects = load_subjects(limit=spec.subject_limit, ids=spec.subject_ids, seed=spec.seed)
    if not subjects:
        raise ValueError("No subjects loaded; check csv_path / md_path in the config.")

    cells: list[Cell] = []
    for arm_id in spec.arms:
        arm = ARMS[arm_id]
        # A stateless arm has no subject dimension: its variation comes from
        # repeated draws, exactly as in the paper's 50-draws-per-cell protocol.
        arm_subjects: list[Subject | None] = list(subjects) if arm.needs_subject else [None]
        draws = spec.subject_draws if arm.needs_subject else spec.draws
        for question in spec.questions:
            for treatment in treatments:
                for subject in arm_subjects:
                    for draw in range(draws):
                        cells.append(Cell(arm_id, question, treatment, subject, draw))
    return cells


def _record(spec: RunSpec, cell: Cell) -> dict:
    context = world_context(cell.subject, cell.treatment.product, seed=spec.seed) if cell.subject else None
    prompt = build_prompt(
        cell.arm,
        cell.question,
        cell.treatment,
        subject=cell.subject,
        context=context,
        grid=spec.grid,
        elicit_fields=spec.elicit_fields,
    )
    row: dict = {
        "key": cell.key,
        "arm": cell.arm,
        "question": cell.question,
        "product_id": cell.treatment.product.id,
        "group": cell.treatment.product.group,
        "category": cell.treatment.product.category,
        "relative_price": cell.treatment.relative_price,
        "price": cell.treatment.price,
        "regular_price": cell.treatment.product.regular_price,
        "subject_id": cell.subject.id if cell.subject else None,
        "draw": cell.draw,
        # Model provenance travels with the answer. Without it, a run whose
        # backend changed halfway is indistinguishable from a real effect.
        "provider": resolve_provider(task="experiment", provider=spec.provider),
    }
    if context is not None:
        # The world's own values, so analysis can score elicited answers
        # against the truth instead of only against each other.
        row["world"] = {
            "last_paid": context.last_paid,
            "competitor_price": context.competitor_price,
            "shelf_life_days": context.shelf_life_days,
        }

    try:
        raw = call_llm(
            prompt.user,
            task="experiment",
            provider=spec.provider,
            system=prompt.system,
            temperature=spec.temperature,
            allow_fallback=False,
        )
    except Exception as exc:  # a dead cell must not kill the sweep
        _LOG.warning("experiment cell failed key=%s error=%s", cell.key, exc)
        row["error"] = str(exc)
        return row

    row["raw"] = raw
    if cell.question == "purchase":
        row["purchase"] = parse_purchase(raw)
    else:
        row["elicited"] = parse_elicit(raw, spec.elicit_fields)
    return row


def _done_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line from an interrupted run
            # Failed cells are retried on resume; that is the point of resuming.
            if row.get("key") and "error" not in row:
                keys.add(row["key"])
    return keys


def _print_plan(spec: RunSpec, cells: list[Cell], todo: list[Cell], results_path: Path) -> None:
    done = len(cells) - len(todo)
    print(
        f"实验 {spec.name}：共 {len(cells)} 次调用"
        f"（已完成 {done}，待跑 {len(todo)}），"
        f"questions={','.join(spec.questions)} temperature={spec.temperature}"
    )
    for arm_id in spec.arms:
        total = sum(1 for cell in cells if cell.arm == arm_id)
        pending = sum(1 for cell in todo if cell.arm == arm_id)
        draws = spec.subject_draws if ARMS[arm_id].needs_subject else spec.draws
        print(f"  {arm_id:<16} {total:>8} 次（待跑 {pending}，每格 {draws} 次采样）")


def run(
    spec: RunSpec,
    *,
    dry_run: bool = False,
    resume: bool = True,
    abort_after: int = 20,
) -> Path:
    """Execute the grid. Returns the path to ``results.jsonl``.

    Aborts if the first ``abort_after`` cells all fail, which is what
    an exhausted quota, a dead endpoint or a bad key look like.
    """
    cells = build_cells(spec)
    out_dir = Path(spec.output_dir) / spec.name
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    (out_dir / "spec.json").write_text(
        json.dumps(
            {
                **{k: (str(v) if isinstance(v, Path) else v) for k, v in vars(spec).items()},
                "grid": list(spec.grid),
                "elicit_fields": list(spec.elicit_fields),
                "total_cells": len(cells),
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if dry_run:
        _print_plan(spec, cells, cells, results_path)
        print(f"dry-run：未发起任何调用。计划写入 {results_path}")
        return results_path

    # Two runs appending to one log duplicate cells and silently
    # double-weight whichever arm was in flight. Fail loudly instead.
    lock_path = out_dir / "run.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"{lock_path} 已存在：同名实验可能正在运行。确认没有其他进程在写 "
            f"{results_path} 后删除该文件再重试。"
        ) from None
    os.write(lock_fd, f"{os.getpid()}\n".encode())
    os.close(lock_fd)

    try:
        return _execute(spec, cells, results_path, resume=resume, abort_after=abort_after)
    finally:
        lock_path.unlink(missing_ok=True)


def _execute(
    spec: RunSpec,
    cells: list[Cell],
    results_path: Path,
    *,
    resume: bool,
    abort_after: int,
) -> Path:
    done = _done_keys(results_path) if resume else set()
    todo = [cell for cell in cells if cell.key not in done]
    _print_plan(spec, cells, todo, results_path)

    lock = threading.Lock()
    completed = 0
    failed = 0
    aborted = False
    with open(results_path, "a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=spec.max_workers) as pool:
            futures = {pool.submit(_record, spec, cell): cell for cell in todo}
            for future in as_completed(futures):
                row = future.result()
                with lock:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    completed += 1
                    failed += 1 if "error" in row else 0
                    # Circuit breaker: an exhausted quota or a bad key fails
                    # every cell the same way, and without this the sweep
                    # cheerfully burns the whole grid producing a file of
                    # errors that *looks* like a finished run.
                    if completed >= abort_after and failed == completed:
                        aborted = True
                        for pending_future in futures:
                            pending_future.cancel()
                        print(
                            f"⛔ 前 {completed} 个格子全部失败，已中止。"
                            f"最后一个错误：{str(row.get('error'))[:200]}",
                            flush=True,
                        )
                        break
                    if completed % 50 == 0 or completed == len(todo):
                        print(
                            f"  进度 {completed}/{len(todo)}（失败 {failed}）",
                            flush=True,
                        )

    succeeded = completed - failed
    print(f"完成：成功 {succeeded}，失败 {failed}" + ("（已中止）" if aborted else ""))
    if aborted:
        raise RuntimeError(
            f"实验中止：前 {completed} 次调用全部失败。结果文件保留在 {results_path}，"
            "修好后端后重跑同一条命令即可续跑（失败的格子会自动重试）。"
        )
    return results_path
