# Locked tests for the R1-5MODEL queue (TASK-1537).
#
# WHY THESE TESTS EXIST: the 5-model stratified queue runs five models back
# to back in ONE invocation with a deterministic persona partition (model i
# answers as pool personas [20i, 20i+20) of every product's 100-persona
# pool), 10 plain draws per (product x level) per model, and a one-token
# GBNF grammar on EVERY purchase call of EVERY model and leg. These tests
# lock the offline contract:
#
#   1. Stratification: the five per-model persona slices are disjoint,
#      deterministic and cover the pool exactly; the plan's per-model call
#      counts are 8,800 (none) + 17,600 (demographics) = 26,400, twenty
#      legs total, 132,000 across the queue.
#   2. Queue resume: a --resume plans exactly the (model, leg) pairs not
#      durably done (completed model legs are skipped as whole units); a
#      partial leg resumes at the CELL level through the same runner the
#      real queue uses (only the missing cells execute); the queue's
#      progress.json is seeded from durable cells and stays monotonic
#      across a restart; results.csv is rebuilt from the authoritative leg
#      records files and then appended per executed cell, so it holds
#      exactly one row per durable cell.
#   3. Grammar plumbing: the request builder puts the queue's grammar in
#      every request when given (and no grammar key when not), and the
#      queue's chat wrapper carries the SAME grammar for every model - no
#      model-specific branching.
#   4. The dry run prints the 5-model queue with per-model 26,400-call
#      plans and the 132,000 total.
#
# Every test runs offline: no model server, no manager, no GPU. The chat
# calls of the leg tests go through a counting fake chat function, exactly
# like the cell-resume tests of TASK-1533.
import csv
import json
import sys
import tempfile
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from launch_cells import (  # noqa: E402
    RESULT_CSV_COLUMNS,
    duplicate_cells,
    results_csv_path,
)
from launch_queue import (  # noqa: E402
    MODEL_QUEUE,
    NONE_LEG_DRAWS,
    PERSONAS_PER_MODEL,
    POOL_PERSONAS_PER_PRODUCT,
    QUEUE_GRAMMAR,
    build_queue_plan,
    persona_slice,
    pending_queue_targets,
    queue_leg_dir,
    queue_leg_jsonl,
    queue_leg_done,
    slice_persona_map,
)
from launch_queue_leg import run_queue_leg  # noqa: E402
from launch_queue_outputs import (  # noqa: E402
    QueueProgress,
    QueueResultsCsv,
    rebuild_results_csv,
)
from launch_support import Settings  # noqa: E402
from launch_sweep import _make_chat  # noqa: E402

# The queue's five models, in the exact user-confirmed order.
EXPECTED_MODEL_ORDER = (
    "openai/gpt-oss-20b",
    "google/gemma-4-26b-a4b",
    "qwen/qwen3.8-27b",
    "nvidia/nemotron-cascade-2-30b-a3b",
    "meta/muse-glimmer",
)
PRODUCTS = [
    {"category": "Soft Drinks", "product": "Cola 12 oz", "regular_price": 1.99},
    {"category": "Chips", "product": "Potato Chips", "regular_price": 2.99},
]
LEVELS = [0.0, 100.0]


def _settings(
    tmp_path: Path, run_name: str = "queue-probe", model: str = "vendor/model"
) -> Settings:
    """One launch configuration pointed at a throwaway directory.

    model defaults to a fake id; leg-level tests pass the queue model of the
    target they drive, exactly as the queue runner replaces the settings per
    model phase.
    """
    return Settings(
        model=model,
        port=8080,
        manager_url="http://127.0.0.1:9",  # nothing listens here; never called
        base_url="http://127.0.0.1:9",
        out=tmp_path,
        run_name=run_name,
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=2,
        progress_every=10,
        products_path="data/configs/unblinding_products.json",
        grammar=QUEUE_GRAMMAR,
    )


def _target(
    model_index: int,
    depth: str,
    blinding: str,
    *,
    calls: int,
) -> dict:
    """One plan leg target for the queue."""
    model = MODEL_QUEUE[model_index]
    return {
        "model": model,
        "model_index": model_index,
        "safe_model": model.replace("/", "_"),
        "depth": depth,
        "blinding": blinding,
        "calls": calls,
    }


def _write_done_queue_leg(
    run_dir: Path,
    target: dict,
    records: int = 1,
    persona: bool = False,
) -> None:
    """Write one FINISHED queue leg's files (records.jsonl + csv + manifest)."""
    leg_dir = queue_leg_dir(run_dir, target)
    leg_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for index in range(records):
        record = {
            "model": target["model"],
            "product": "Cola 12 oz",
            "treatment_value": 0.0 if index % 2 == 0 else 100.0,
            "blinding": target["blinding"],
            "persona_depth": target["depth"],
            "succeeded": True,
            "parsed_purchase": True,
            "elapsed_seconds": 0.1,
        }
        if persona:
            record["persona_index"] = index
        lines.append(json.dumps(record))
    (leg_dir / "records.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (leg_dir / "records.csv").write_text("", encoding="utf-8")
    (leg_dir / "manifest.json").write_text(
        json.dumps({"depth": target["depth"], "blinding": target["blinding"]}),
        encoding="utf-8",
    )


class _CountingChat:
    """A fake chat_fn that counts calls and answers "purchase"."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, messages, temperature):
        self.calls += 1
        return "purchase"


def _full_plan() -> dict:
    """The plan for 2 products x 2 levels (small enough for offline runs)."""
    return build_queue_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS)


# ---------------------------------------------------------------------------
# 1. Stratification: persona slices + per-model call counts
# ---------------------------------------------------------------------------


def test_five_persona_slices_are_disjoint_and_cover_the_pool_exactly():
    """persona_slice gives model i the deterministic pool range [20i, 20i+20);
    the five ranges are disjoint and cover the 100-persona pool exactly."""
    slices = [persona_slice(index) for index in range(len(MODEL_QUEUE))]
    assert slices == [
        (0, 20),
        (20, 40),
        (40, 60),
        (60, 80),
        (80, 100),
    ]
    # Deterministic: the same call twice gives the same range.
    assert persona_slice(3) == persona_slice(3)
    # Disjoint and cover the pool exactly, in order.
    seen: list[int] = []
    for start, stop in slices:
        assert start < stop
        assert not (seen and start < seen[-1])  # ordered, never overlapping
        seen.extend(range(start, stop))
    assert seen == list(range(POOL_PERSONAS_PER_PRODUCT))
    # A pool index outside the 5-model queue refuses instead of slicing empty.
    try:
        persona_slice(len(MODEL_QUEUE))
    except ValueError:
        pass
    else:
        raise AssertionError("persona_slice must refuse an out-of-queue index")


def test_persona_map_slices_are_deterministic_disjoint_and_cover_the_pool():
    """slice_persona_map hands each model exactly its 20 pool personas, the
    five maps are disjoint and together cover the pool, and the shared map
    itself is never mutated."""
    pool = {
        "Cola 12 oz": {
            "category": "Soft Drinks",
            "regular_price": 1.99,
            "personas": [{"pid": index} for index in range(POOL_PERSONAS_PER_PRODUCT)],
        }
    }
    model_maps = [slice_persona_map(pool, index) for index in range(len(MODEL_QUEUE))]
    assert len(pool["Cola 12 oz"]["personas"]) == POOL_PERSONAS_PER_PRODUCT  # untouched
    seen_pids: list[int] = []
    for index, sliced in enumerate(model_maps):
        pids = [persona["pid"] for persona in sliced["Cola 12 oz"]["personas"]]
        assert len(pids) == PERSONAS_PER_MODEL
        start, stop = persona_slice(index)
        assert pids == list(range(start, stop))  # deterministic indices
        seen_pids.extend(pids)
    assert seen_pids == list(range(POOL_PERSONAS_PER_PRODUCT))  # exact cover
    # Re-slicing is deterministic (same personas, same order).
    again = slice_persona_map(pool, 4)
    assert [p["pid"] for p in again["Cola 12 oz"]["personas"]] == [
        p["pid"] for p in model_maps[4]["Cola 12 oz"]["personas"]
    ]
    # A pool too short for the model's slice refuses instead of silently
    # dropping cells.
    short_pool = {
        "Cola 12 oz": {
            "category": "Soft Drinks",
            "regular_price": 1.99,
            "personas": [{"pid": i} for i in range(80)],
        }
    }
    try:
        slice_persona_map(short_pool, 4)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a short pool must refuse the slice")


def test_queue_plan_call_counts_per_model_and_total():
    """Per model: 2 x 40 x 11 x 10 = 8,800 none calls + 2 x 40 x 20 x 11 =
    17,600 demographics calls = 26,400; 20 legs; 132,000 across the queue."""
    plan = build_queue_plan(40, 11, levels=[float(x) for x in range(0, 220, 20)])
    assert [meta["model"] for meta in plan["models"]] == list(EXPECTED_MODEL_ORDER)
    assert len(plan["legs"]) == 20
    assert plan["k"] == POOL_PERSONAS_PER_PRODUCT
    assert plan["draws"] == NONE_LEG_DRAWS
    assert plan["per_model_personas"] == PERSONAS_PER_MODEL
    per_model_none = {}
    per_model_persona = {}
    for leg in plan["legs"]:
        if leg["depth"] == "none":
            per_model_none[leg["model"]] = (
                per_model_none.get(leg["model"], 0) + leg["calls"]
            )
        else:
            per_model_persona[leg["model"]] = (
                per_model_persona.get(leg["model"], 0) + leg["calls"]
            )
    for model in EXPECTED_MODEL_ORDER:
        assert per_model_none[model] == 8_800
        assert per_model_persona[model] == 17_600
        meta = next(m for m in plan["models"] if m["model"] == model)
        assert meta["total_calls"] == 26_400
    assert sum(leg["calls"] for leg in plan["legs"]) == 132_000
    assert plan["sweep_calls"] == 132_000
    # Per-blinding leg sizes: none 4,400 each, demographics 8,800 each, and
    # the four legs of each model appear in the queue's depth x blinding order.
    first_four = plan["legs"][:4]
    assert [(leg["depth"], leg["blinding"]) for leg in first_four] == [
        ("none", "blinded"),
        ("none", "unblinded"),
        ("demographics", "blinded"),
        ("demographics", "unblinded"),
    ]
    assert [leg["calls"] for leg in first_four] == [4_400, 4_400, 8_800, 8_800]


# ---------------------------------------------------------------------------
# 2. Queue resume: completed model legs skipped, cell-level leg resume,
#    progress monotonic, results.csv exactly-once
# ---------------------------------------------------------------------------


def test_queue_resume_plans_only_legs_missing_from_disk():
    """A run whose first model's four legs (and one extra leg) are finished
    on disk resumes by planning exactly the missing (model, leg) pairs - the
    completed model legs are skipped as whole units."""
    plan = _full_plan()  # 2 products x 2 levels; 20 legs
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        done = []
        for target in plan["legs"]:
            if target["model_index"] == 0:
                done.append(target)
            elif target["model_index"] == 1 and target["blinding"] == "blinded":
                done.append(target)
        for target in done:
            _write_done_queue_leg(run_dir, target, records=2)
        for target in done:
            assert queue_leg_done(run_dir, target)
        pending = pending_queue_targets(run_dir, plan["legs"], resume=True)
        pending_keys = {
            (leg["model_index"], leg["depth"], leg["blinding"]) for leg in pending
        }
        done_keys = {(t["model_index"], t["depth"], t["blinding"]) for t in done}
        assert done_keys.isdisjoint(pending_keys)
        assert len(pending) == 20 - len(done)
        # A fresh (non-resume) start plans every leg regardless of disk state.
        assert len(pending_queue_targets(run_dir, plan["legs"], resume=False)) == 20
        # A partial records file without the leg's csv+manifest is NOT done.
        partial = _target(2, "none", "blinded", calls=40)
        partial_dir = queue_leg_dir(run_dir, partial)
        partial_dir.mkdir(parents=True)
        (partial_dir / "records.jsonl").write_text(
            json.dumps({"succeeded": True}) + "\n", encoding="utf-8"
        )
        assert not queue_leg_done(run_dir, partial)
        assert partial in pending_queue_targets(run_dir, plan["legs"], resume=True)


def test_run_queue_leg_continues_partial_plain_leg_skipping_done_cells():
    """The queue's own leg runner continues a partial leg at the CELL level:
    8 planned plain cells, 5 durable -> exactly 3 chat calls, and the
    completed leg files hold every planned cell exactly once."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        target = _target(0, "none", "blinded", calls=8)
        settings = _settings(tmp_path, model=target["model"])
        run_dir = settings.out / settings.run_name
        run_dir.mkdir(parents=True)
        jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, target))
        # The first 5 cells of the plain enumeration (product x level x draw).
        draws = 2
        lines = []
        for product in PRODUCTS:
            for level in LEVELS:
                for draw in range(draws):
                    if len(lines) >= 5:
                        break
                    lines.append(
                        json.dumps(
                            {
                                "model": target["model"],
                                "product": product["product"],
                                "treatment_value": level,
                                "blinding": "blinded",
                                "persona_depth": "none",
                                "succeeded": True,
                                "parsed_purchase": True,
                                "elapsed_seconds": 0.1,
                            }
                        )
                    )
                if len(lines) >= 5:
                    break
            if len(lines) >= 5:
                break
        jsonl.parent.mkdir(parents=True)
        jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
        plan = {**_full_plan(), "legs": [target]}
        chat = _CountingChat()
        log: list[str] = []
        results: list[dict] = []
        run_queue_leg(
            settings,
            plan,
            PRODUCTS,
            None,
            run_dir,
            chat,
            target,
            results,
            log.append,
            None,
            None,
        )
        assert chat.calls == 3  # exactly the 3 missing cells
        assert len(results) == 1 and results[0]["ok"] is True
        assert results[0]["records"] == 8
        from launch_cells import scan_leg_jsonl

        records, torn = scan_leg_jsonl(jsonl)
        assert len(records) == 8 and torn == 0
        assert duplicate_cells(records, persona=False, expected_per_group=draws) == []
        leg_dir = queue_leg_dir(run_dir, target)
        assert (leg_dir / "records.csv").exists()
        assert (leg_dir / "manifest.json").exists()


def test_run_queue_leg_resumes_partial_persona_leg_at_cell_level():
    """The demographics leg of the queue resumes at the cell level too: a
    model's persona slice runs (product x persona x level) cells and only the
    missing ones execute after a partial records file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Model 1 answers pool personas [20, 40): 20 personas x 2 levels = 40
        # cells; 6 durable -> 34 missing.
        target = _target(1, "demographics", "blinded", calls=40)
        settings = _settings(tmp_path, model=target["model"])
        run_dir = settings.out / settings.run_name
        run_dir.mkdir(parents=True)
        personas_by_product = {
            "Cola 12 oz": {
                "category": "Soft Drinks",
                "regular_price": 1.99,
                "personas": [
                    {"pid": index} for index in range(POOL_PERSONAS_PER_PRODUCT)
                ],
            }
        }
        # Model 1 answers pool personas [20, 40): 20 personas x 2 levels = 40
        # cells; 6 durable -> 34 missing.
        target = _target(1, "demographics", "blinded", calls=40)
        jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, target))
        lines = []
        for persona_index in range(20):
            for level in LEVELS:
                if len(lines) >= 6:
                    break
                lines.append(
                    json.dumps(
                        {
                            "model": target["model"],
                            "product": "Cola 12 oz",
                            "treatment_value": level,
                            "blinding": "blinded",
                            "persona_depth": "demographics",
                            "persona_index": persona_index,
                            "succeeded": True,
                            "parsed_purchase": True,
                            "elapsed_seconds": 0.1,
                        }
                    )
                )
            if len(lines) >= 6:
                break
        jsonl.parent.mkdir(parents=True)
        jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
        plan = {**_full_plan(), "legs": [target]}
        chat = _CountingChat()
        log: list[str] = []
        results: list[dict] = []
        run_queue_leg(
            settings,
            plan,
            PRODUCTS,
            personas_by_product,
            run_dir,
            chat,
            target,
            results,
            log.append,
            None,
            None,
        )
        assert chat.calls == 34  # only the missing cells executed
        assert len(results) == 1 and results[0]["ok"] is True
        assert results[0]["records"] == 40
        from launch_cells import scan_leg_jsonl

        records, torn = scan_leg_jsonl(jsonl)
        assert len(records) == 40 and torn == 0
        assert duplicate_cells(records, persona=True) == []
        # The executed personas belong to model 1's pool slice [20, 40).
        assert {r["persona_index"] for r in records} == set(range(0, 20))


def test_queue_progress_seeds_durable_cells_and_stays_monotonic():
    """QueueProgress seeds each leg's done count from the durable cells a
    resume finds on disk and only counts upward, so progress.json across a
    restarted run is monotonic; the snapshot reports per-model and total."""
    plan = _full_plan()
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        log: list[str] = []
        progress = QueueProgress(run_dir, plan["legs"], log.append)
        target0 = plan["legs"][0]
        progress.set_leg(target0, done_at_start=5)  # durable prefix
        progress.note(target0, succeeded=True, force=True)  # one now
        payload = progress.snapshot()
        assert payload["cells_done"] == 6
        assert payload["cells_total"] == sum(leg["calls"] for leg in plan["legs"])
        per_model = payload["per_model"]
        assert list(per_model) == [m.replace("/", "_") for m in EXPECTED_MODEL_ORDER]
        safe0 = target0["safe_model"]
        assert per_model[safe0]["per_leg"]["none_blinded"] == {"done": 6, "total": 40}
        assert per_model[safe0]["done"] == 6
        # A "second invocation" (resume) seeds from the same durable state:
        # the done counts only ever grow.
        resumed = QueueProgress(run_dir, plan["legs"], log.append)
        resumed.set_leg(target0, done_at_start=6)
        resumed.note(target0, succeeded=True, force=True)
        second = resumed.snapshot()
        assert second["cells_done"] == 7
        assert second["cells_done"] >= payload["cells_done"]
        for key in (
            "cells_done",
            "cells_total",
            "per_model",
            "calls_per_sec_measured",
            "eta_seconds",
            "parse_rate_so_far",
            "updated_at",
        ):
            assert key in second
        resumed.finish()
        written = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
        assert written["cells_done"] == 7
        assert written["cells_total"] == second["cells_total"]


def _plain_record(target: dict, product: str, level: float, draw: int) -> dict:
    """One synthetic plain-leg record as the sweep kit writes it."""
    return {
        "model": target["model"],
        "product": product,
        "treatment_value": level,
        "blinding": target["blinding"],
        "persona_depth": "none",
        "succeeded": True,
        "parsed_purchase": draw % 2 == 0,
        "elapsed_seconds": 0.1,
    }


def _write_partial_plain_leg(
    run_dir: Path, target: dict, draws: int, done_cells: int
) -> Path:
    """Write the first done_cells cells of a plain leg's records file."""
    jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, target))
    jsonl.parent.mkdir(parents=True)
    lines = []
    for product in PRODUCTS:
        for level in LEVELS:
            for draw in range(draws):
                if len(lines) >= done_cells:
                    break
                lines.append(
                    json.dumps(_plain_record(target, product["product"], level, draw))
                )
            if len(lines) >= done_cells:
                break
        if len(lines) >= done_cells:
            break
    jsonl.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return jsonl


def _csv_rows(path: Path) -> list[dict]:
    """Read the results.csv rows (minus the header)."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_results_csv_exactly_one_row_per_cell_across_a_resume():
    """results.csv is rebuilt from the authoritative leg records files at an
    invocation start and then appended per executed cell, so after a partial
    leg is resumed and finished the file holds exactly one row per cell with
    stable draw ids - no duplicates and no missing cells."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        target = _target(0, "none", "blinded", calls=8)
        settings = _settings(tmp_path, model=target["model"])
        run_dir = settings.out / settings.run_name
        run_dir.mkdir(parents=True)
        regular_prices = {p["product"]: p["regular_price"] for p in PRODUCTS}
        log: list[str] = []
        # Invocation 1 crashed after 5 durable cells (rows were appended
        # per cell while it ran). The resume REBUILDS from the records file,
        # then the appender continues the missing draws.
        draws = 2
        jsonl = _write_partial_plain_leg(run_dir, target, draws, done_cells=5)
        plan = {**_full_plan(), "legs": [target]}
        seed = rebuild_results_csv(run_dir, plan["legs"], regular_prices, log.append)
        rows = _csv_rows(results_csv_path(run_dir))
        assert len(rows) == 5  # rebuilt from the durable prefix
        assert list(rows[0]) == RESULT_CSV_COLUMNS
        assert rows[0]["condition_depth"] == "none"
        assert rows[0]["condition_blinding"] == "blinded"
        assert rows[0]["parsed"] == "True"
        appender = QueueResultsCsv(run_dir, regular_prices, seed)
        chat = _CountingChat()
        results: list[dict] = []
        run_queue_leg(
            settings,
            plan,
            PRODUCTS,
            None,
            run_dir,
            chat,
            target,
            results,
            log.append,
            None,
            appender,
        )
        appender.close()
        assert chat.calls == 3
        assert len(results) == 1 and results[0]["ok"] is True
        rows = _csv_rows(results_csv_path(run_dir))
        assert len(rows) == 8
        # Exactly one row per {model, product, price, condition, draw_id}.
        keys = [
            (
                r["model"],
                r["product"],
                r["price"],
                r["condition_depth"],
                r["condition_blinding"],
                r["draw_id"],
            )
            for r in rows
        ]
        assert len(set(keys)) == 8
        # draw ids are per (product, price, blinding) group: two draws each.
        by_group: dict[tuple, list[str]] = {}
        for r in rows:
            by_group.setdefault((r["model"], r["product"], r["price"]), []).append(
                r["draw_id"]
            )
        assert sorted(len(ids) for ids in by_group.values()) == [2, 2, 2, 2]
        assert all(sorted(ids) == ["0", "1"] for ids in by_group.values())
        # The group that the crash split (Potato Chips at the 0% level: one
        # durable draw, one executed after the resume) is numbered 0 and 1 -
        # the resumed execution continued after the durable prefix instead of
        # restarting at 0 (which would duplicate draw 0 of that cell).
        split_group = next(
            ids
            for (model, product, price), ids in by_group.items()
            if product == "Potato Chips" and price == "0.0" and model == target["model"]
        )
        assert sorted(split_group) == ["0", "1"]
        # Rebuilding again after the leg finished still yields 8 rows (a
        # resumed invocation never duplicates durable cells).
        rebuild_results_csv(run_dir, plan["legs"], regular_prices, log.append)
        assert len(_csv_rows(results_csv_path(run_dir))) == 8
        assert jsonl.exists()


def test_resume_of_fully_completed_queue_is_a_safe_noop_without_loading_models():
    """--resume against a queue run whose 20 legs are all durably done is a
    safe no-op: it never loads a model through the manager, keeps every leg
    in the final manifest exactly once and marks the run complete."""
    from dataclasses import replace

    from launch_5model import run_queue
    from launch_grid import _parse_args, _settings_from

    plan = _full_plan()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        args = _parse_args(
            [
                "--profile",
                "R1-5MODEL",
                "--run-name",
                "queue-probe",
                "--resume",
            ]
        )
        settings = replace(_settings_from(args, "queue-probe"), out=tmp_path)
        run_dir = settings.out / settings.run_name
        run_dir.mkdir(parents=True)
        for target in plan["legs"]:
            _write_done_queue_leg(
                run_dir,
                target,
                records=int(target["calls"]),
                persona=target["depth"] != "none",
            )
        (run_dir / "pools.json").write_text(
            json.dumps({"k": plan["k"], "pool_seed": 42, "products": 2}),
            encoding="utf-8",
        )
        (run_dir / "manifest.json").write_text(
            json.dumps({"state": "running", "started": "2026-01-01T00:00:00"}),
            encoding="utf-8",
        )

        import launch_5model as queue_module

        def forbidden(*_args, **_kwargs):
            raise AssertionError("a fully resumed queue must not load a model")

        original_load = queue_module._load_model
        queue_module._load_model = forbidden
        try:
            exit_code = run_queue(args, plan, [], Path("products.json"), settings)
        finally:
            queue_module._load_model = original_load
        assert exit_code == 0
        payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert payload["state"] == "complete"
        assert payload["ok"] is True
        merged = [
            (leg["model_index"], leg["depth"], leg["blinding"])
            for leg in payload["legs"]
        ]
        expected = [(t["model_index"], t["depth"], t["blinding"]) for t in plan["legs"]]
        assert merged == expected
        assert len(merged) == len(set(merged))  # every leg exactly once


# ---------------------------------------------------------------------------
# 3. Grammar plumbing: every model and leg, no branching
# ---------------------------------------------------------------------------


def test_request_builder_includes_grammar_when_given():
    """build_sweep_chat_fn puts the queue grammar in EVERY request when
    grammar is given, and leaves the payload grammar-free when it is not."""
    from unblinding_sweep import build_sweep_chat_fn  # type: ignore[import-not-found]

    captured: list[dict] = []

    def fake_post(url: str, payload: dict, timeout: float):
        captured.append(payload)
        body = '{"choices": [{"message": {"content": "purchase"}}]}'
        return 200, body

    import unblinding_sweep as sweep_module

    original = sweep_module._post_json
    sweep_module._post_json = fake_post
    try:
        chat = build_sweep_chat_fn(
            "http://127.0.0.1:9", "openai/gpt-oss-20b", 16, 30.0, grammar=QUEUE_GRAMMAR
        )
        messages = [{"role": "user", "content": "buy?"}]
        assert chat(messages, 1.0) == "purchase"
        assert chat(messages, 1.0) == "purchase"
        # Every request carries the grammar (no model- or leg-specific branch).
        assert [p.get("grammar") for p in captured] == [QUEUE_GRAMMAR, QUEUE_GRAMMAR]
        assert "max_tokens" in captured[0]
        captured.clear()
        plain = build_sweep_chat_fn("http://127.0.0.1:9", "qwen/qwen3.8-27b", 16, 30.0)
        plain(messages, 1.0)
        assert "grammar" not in captured[0]
    finally:
        sweep_module._post_json = original


def test_queue_chat_uses_the_same_grammar_for_every_model():
    """The queue's counting chat wrapper (the same one every leg uses) is
    built with the queue grammar for EVERY model of the queue - a single
    code path and a single grammar, no model-specific branching."""
    import launch_support as support_module

    recorded: list[tuple[str, str | None]] = []

    def recorder(base_url, model, max_tokens, timeout, grammar=None):
        recorded.append((model, grammar))
        return _CountingChat()

    original = support_module._SWEEP.build_sweep_chat_fn
    support_module._SWEEP.build_sweep_chat_fn = recorder
    try:
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(Path(tmp))
            for model in EXPECTED_MODEL_ORDER:
                from dataclasses import replace

                model_settings = replace(settings, model=model)
                chat_fn, state, _abort = _make_chat(
                    model_settings,
                    10,
                    lambda *a: None,
                    grammar=QUEUE_GRAMMAR,
                )
                assert chat_fn([{"role": "user", "content": "buy?"}], 1.0) == "purchase"
                assert state["done"] == 1 and state["parsed"] == 1
    finally:
        support_module._SWEEP.build_sweep_chat_fn = original
    assert [model for model, _grammar in recorded] == list(EXPECTED_MODEL_ORDER)
    assert {grammar for _model, grammar in recorded} == {QUEUE_GRAMMAR}


# ---------------------------------------------------------------------------
# 4. The dry run prints the 5-model queue with the real call counts
# ---------------------------------------------------------------------------


def test_queue_dry_run_prints_the_five_model_plan(capsys):
    """launch_grid --profile R1-5MODEL --dry-run prints the 5-model queue
    with per-model 26,400-call plans (8,800 none + 17,600 demographics per
    model) and the 132,000 total - offline, no model server touched."""
    from launch_grid import main

    assert main(["--profile", "R1-5MODEL", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "R1-5MODEL launch plan (dry run)" in out
    for index, model in enumerate(EXPECTED_MODEL_ORDER):
        assert f"[{index}] {model}" in out
    assert QUEUE_GRAMMAR in out
    assert "8,800 calls" in out and "17,600 calls" in out
    assert "26,400" in out
    assert "132,000 total (5 models x 26,400)" in out
    assert "results.csv" in out and "progress.json" in out
