# Locked tests for the R1-YESNO-QWENEXT RUNNER WIRING - cell-granular
# resume on the shared slice, and the untouched-neighbour guards
# (TASK-1631, RED phase; tests ONLY - no implementation lives here).
#
# Companion to tests/test_launch_qwenext_wiring.py (launcher entry + queue
# execution). Locked here, all offline (no manager, no GPU, no server):
#
#   (1) SHARED-SLICE RESUME: a partial QWENEXT demographics leg resumes at
#       the CELL level and answers ONLY pool personas [40, 60) - the exact
#       slice qwen/qwen3.8-27b answered in R1-YESNO - never the 5-model
#       partition slice [20i, 20i+20) that run_queue_leg's default
#       persona slicing produces today.
#   (2) DURABLE FINALIZE: a fully durable leg finalizes from disk with
#       zero scoring calls and stamps the shared [40, 60) slice on its
#       leg manifest.
#   (3) NEIGHBOURS UNTOUCHED: building the QWENEXT plan leaves the
#       existing profiles' plan builders and registry entries unchanged.
#
# The fake scorer/chat pattern follows tests/test_launch_queue.py's
# counting fakes; no test here touches a real server.
import json
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from launch_queue import (  # noqa: E402
    LOGP_PROFILE,
    MODEL_QUEUE,
    YESNO_PROFILE,
    build_logprob_plan,
    build_queue_plan,
    queue_leg_dir,
    queue_leg_jsonl,
)
from launch_queue_leg import run_queue_leg  # noqa: E402
from launch_support import PROFILES, Settings  # noqa: E402
from launch_yesno_qwenext import (  # noqa: E402
    QWENEXT_PROFILE,
    build_qwenext_plan,
)

PRODUCTS = [
    {"category": "Soft Drinks", "product": "Cola 12 oz", "regular_price": 1.99},
    {"category": "Chips", "product": "Potato Chips", "regular_price": 2.99},
]
LEVELS = [0.0, 100.0]
FULL_LEVELS = [float(x) for x in range(0, 220, 20)]
POOL_SIZE = 100  # every product's shared pool holds 100 personas


def _settings(tmp_path: Path, run_name: str) -> Settings:
    """One QWENEXT launch configuration pointed at a throwaway directory."""
    return Settings(
        model="vendor/model",
        port=8080,
        manager_url="http://127.0.0.1:9",  # nothing listens here; never called
        base_url="http://127.0.0.1:9",
        out=tmp_path,
        run_name=run_name,
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=1,
        progress_every=10,
        products_path="products.json",
        grammar=None,
        logprob_mode="first_token",
        response_format="yes/no",
    )


def _plan() -> dict:
    """The QWENEXT plan for 2 products x 2 levels (offline-sized)."""
    return build_qwenext_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS)


def _persona_record(leg: dict, product: str, level: float, pid: int) -> dict:
    """One synthetic durable demographics record on the shared slice."""
    return {
        "model": leg["model"],
        "product": product,
        "treatment_value": level,
        "blinding": leg["blinding"],
        "persona_depth": "demographics",
        "persona": {"pid": pid},
        "persona_index": pid - 40,
        "succeeded": True,
        "parsed_purchase": True,
        "elapsed_seconds": 0.1,
    }


def _leg_manifest(run_dir: Path, leg: dict) -> dict:
    """Read one leg's manifest.json from disk."""
    return json.loads(
        (queue_leg_dir(run_dir, leg) / "manifest.json").read_text(encoding="utf-8")
    )


def _record_pids_by_product(records: list[dict]) -> dict[str, set[int]]:
    """The pool persona ids each product's records were answered with."""
    pids: dict[str, set[int]] = {}
    for record in records:
        pids.setdefault(record["product"], set()).add(record["persona"]["pid"])
    return pids


def _pool_map() -> dict:
    """The shared 100-persona pool map for both products (pid-tagged)."""
    return {
        product["product"]: {
            "category": product["category"],
            "regular_price": product["regular_price"],
            "personas": [{"pid": i} for i in range(POOL_SIZE)],
        }
        for product in PRODUCTS
    }


def _partial_shared_slice_leg(tmp_path: Path, leg: dict, done_cells: int) -> Path:
    """A QWENEXT demographics leg whose first done_cells cells (pool pids
    40, 41, 42 x the two levels, Cola first) are already durable."""
    settings = _settings(tmp_path, "qwenext-resume-probe")
    run_dir = settings.out / settings.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, leg))
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for pid in (40, 41, 42):
        for level in LEVELS:
            if len(lines) >= done_cells:
                break
            lines.append(json.dumps(_persona_record(leg, "Cola 12 oz", level, pid)))
        if len(lines) >= done_cells:
            break
    jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


def _scoring_calls_counter():
    """A counting fake scorer plus its call counter dict."""
    calls = {"scored": 0}

    def counting_scorer(_messages):
        calls["scored"] += 1
        return {"succeeded": True, "parsed_purchase": True, "raw_content": " yes"}

    return calls, counting_scorer


# ---------------------------------------------------------------------------
# (1) Shared-slice resume: a partial leg answers ONLY pool personas 40-59
# ---------------------------------------------------------------------------


def test_qwenext_resume_of_a_partial_demographics_leg_answers_only_the_shared_slice(
    tmp_path,
):
    """A partial QWENEXT demographics leg resumes at the CELL level on the
    SHARED slice: of 80 planned cells (2 products x 20 personas x 2 levels)
    with 6 durable (pids 40-42), exactly 74 scoring calls run and the
    finished leg holds pool personas 40-59 ONLY - stamped on the leg
    manifest too."""
    plan = _plan()
    leg = next(
        target
        for target in plan["legs"]
        if target["model_index"] == 0
        and target["depth"] == "demographics"
        and target["blinding"] == "blinded"
    )
    run_dir = _partial_shared_slice_leg(tmp_path, leg, done_cells=6)
    calls, counting_scorer = _scoring_calls_counter()

    def forbidden_chat(_messages, _temperature):
        raise AssertionError("a first_token logprob leg must never sample via chat")

    settings = _settings(tmp_path, "qwenext-resume-probe")
    results: list[dict] = []
    run_queue_leg(
        settings,
        {**plan, "legs": [leg]},
        PRODUCTS,
        _pool_map(),
        run_dir,
        forbidden_chat,
        leg,
        results,
        lambda _text: None,
        None,
        None,
        scorer_fn=counting_scorer,
    )
    assert len(results) == 1 and results[0]["ok"] is True, (
        f"the resumed leg must complete; got {results}"
    )
    assert calls["scored"] == leg["calls"] - 6, (
        f"resume must execute exactly the {leg['calls'] - 6} missing cells; "
        f"scored {calls['scored']}"
    )
    records = [
        json.loads(line)
        for line in queue_leg_jsonl(queue_leg_dir(run_dir, leg))
        .read_text()
        .splitlines()
        if line
    ]
    assert len(records) == leg["calls"]
    pids = _record_pids_by_product(records)
    assert set(pids) == {"Cola 12 oz", "Potato Chips"}
    for product, answered in pids.items():
        assert answered == set(range(40, 60)), (
            f"{product}: a QWENEXT leg must answer ONLY the shared "
            f"[40, 60) slice qwen3.8-27b answered; answered {sorted(answered)}"
        )
    assert _leg_manifest(run_dir, leg)["persona_slice"] == [40, 60]


# ---------------------------------------------------------------------------
# (2) Durable finalize: zero calls, shared-slice stamp
# ---------------------------------------------------------------------------


def test_qwenext_fully_done_leg_finalizes_offline_and_stamps_the_shared_slice(
    tmp_path,
):
    """A QWENEXT leg whose every cell is already durable (a crash after the
    last record but before finalization) finalizes from disk with zero
    scoring calls and stamps the shared [40, 60) slice on its manifest."""
    plan = _plan()
    leg = next(
        target
        for target in plan["legs"]
        if target["model_index"] == 1
        and target["depth"] == "demographics"
        and target["blinding"] == "unblinded"
    )
    settings = _settings(tmp_path, "qwenext-done-probe")
    run_dir = settings.out / settings.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    leg_dir = queue_leg_dir(run_dir, leg)
    leg_dir.mkdir(parents=True)
    lines = [
        json.dumps(_persona_record(leg, product, level, 40 + pid))
        for product in ("Cola 12 oz", "Potato Chips")
        for pid in range(20)
        for level in LEVELS
    ]
    assert len(lines) == leg["calls"]
    queue_leg_jsonl(leg_dir).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (leg_dir / "records.csv").write_text("", encoding="utf-8")
    (leg_dir / "manifest.json").write_text("{}", encoding="utf-8")

    scored = {"count": 0}

    def forbidden_scorer(_messages):
        scored["count"] += 1
        raise AssertionError("a fully durable leg must not score anything")

    results: list[dict] = []
    run_queue_leg(
        settings,
        {**plan, "legs": [leg]},
        PRODUCTS,
        None,
        run_dir,
        None,
        leg,
        results,
        lambda _text: None,
        None,
        None,
        scorer_fn=forbidden_scorer,
    )
    assert len(results) == 1 and results[0]["ok"] is True
    assert scored["count"] == 0, "a fully durable leg finalizes offline"
    assert _leg_manifest(run_dir, leg)["persona_slice"] == [40, 60], (
        "the finalized leg manifest must stamp the SHARED [40, 60) slice, "
        f"not the 5-model partition slice: {_leg_manifest(run_dir, leg)}"
    )


# ---------------------------------------------------------------------------
# (3) Neighbours untouched: existing profiles stay exactly as they are
# ---------------------------------------------------------------------------


def test_qwenext_plan_building_leaves_the_existing_profile_plans_unchanged():
    """Building the QWENEXT plan must not disturb the pre-existing plan
    builders: R1-5MODEL keeps its 5-model partition and 132,000 calls,
    R1LP and R1-YESNO keep their logprob geometry and their own stamps."""
    qwenext_plan = build_qwenext_plan(40, len(FULL_LEVELS), levels=FULL_LEVELS)
    queue_plan = build_queue_plan(40, len(FULL_LEVELS), levels=FULL_LEVELS)
    assert queue_plan["profile"] == "R1-5MODEL"
    assert [m["model"] for m in queue_plan["models"]] == list(MODEL_QUEUE)
    assert queue_plan["sweep_calls"] == 132_000
    assert len(queue_plan["legs"]) == 20
    lp_plan = build_logprob_plan(40, len(FULL_LEVELS), levels=FULL_LEVELS)
    assert lp_plan["profile"] == LOGP_PROFILE == "R1LP"
    assert lp_plan["sweep_calls"] == 92_400
    yesno_plan = build_logprob_plan(
        40, len(FULL_LEVELS), levels=FULL_LEVELS, profile=YESNO_PROFILE
    )
    assert yesno_plan["profile"] == "R1-YESNO"
    assert yesno_plan["sweep_calls"] == 92_400
    # ...and the QWENEXT plan kept its own stamp all along.
    assert qwenext_plan["profile"] == QWENEXT_PROFILE


def test_profile_registry_keeps_every_existing_profile_entry():
    """Registering R1-YESNO-QWENEXT must not move any existing profile's
    registry entry (the --profile choices and their persona counts)."""
    assert PROFILES.get("R1") == 100
    assert PROFILES.get("FULL") == 500
    assert PROFILES.get("R1-5MODEL") == 100
    assert PROFILES.get("R1LP") == 100
    assert PROFILES.get("R1-YESNO") == 100
