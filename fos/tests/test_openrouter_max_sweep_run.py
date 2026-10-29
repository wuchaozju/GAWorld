# Locked tests for the OPENROUTER QWEN3.8-MAX GRAMMAR SWEEP (TASK-1653,
# RED phase; tests ONLY - no implementation lives here): the RUN half.
# Where tests/test_openrouter_max_sweep.py pins the pure spec (constants,
# plan, parsing, retries), this file pins what a run DOES - all through a
# FAKE transport, all offline (sockets refused, no API key, no GPU):
#
#   (1) PROMPT PARITY (the core of the task): every request's messages are
#       built by the EXISTING sweep_kit builders - system prompts
#       byte-equal build_blinded_system_prompt() /
#       build_unblinded_system_prompt(design), user prompts byte-equal
#       build_purchase_user_prompt(...) at _price_for_level prices for the
#       none legs, and the _persona_user_prompt path of run_persona_sweep
#       for the demographics legs; temperatures 1.0 / 0.0; the pinned
#       response_format on every request.
#   (2) RECORDS: one self-describing record per call (model, condition,
#       product, level, price, persona/draw index, raw, decision, parsed,
#       usage, cost, timestamp); unparsable answers recorded as
#       unclassified, never dropped.
#   (3) DURABILITY: per-leg records.jsonl under
#       R1-API-QWEN38MAX-<ts>/<model-safe>/<depth>_<blinding>/, plus
#       manifest.json and progress.json; resume skips durable cells.
#   (4) MONEY: the cost guard hard-aborts before exceeding --max-cost.
#   (5) OFFLINE CLI: --dry-run prints the plan with every socket refused;
#       a run without OPENROUTER_API_KEY fails fast; the key never leaks
#       into any artifact.
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import unblinding_sweep as sweep_cli  # noqa: E402
from fos.experiments import sweep_kit  # noqa: E402
from tests.openrouter_max_sweep_spec import (  # noqa: E402
    EXACT_RESPONSE_FORMAT,
    LEVELS,
    PRODUCTS,
    FakeTransport,
    expected_design,
    expected_none_users,
    expected_persona_users,
    forbid_sockets,
    write_pools_dir,
)

import openrouter_max_sweep as harness  # noqa: E402


def _plan_for(depth: str, blinding: str) -> dict:
    """A mini single-leg plan: 2 products x 2 levels, draws=2, seed 42."""
    plan = harness.build_max_sweep_plan(
        len(PRODUCTS), len(LEVELS), levels=LEVELS, draws=2
    )
    legs = [
        leg
        for leg in plan["legs"]
        if leg["depth"] == depth and leg["blinding"] == blinding
    ]
    assert len(legs) == 1
    return {**plan, "legs": legs, "sweep_calls": legs[0]["calls"]}


def _full_mini_plan() -> dict:
    """All four legs at the mini geometry (2 products x 2 levels x 2 draws
    for the none legs, the 4 personas for the demographics legs)."""
    return harness.build_max_sweep_plan(
        len(PRODUCTS), len(LEVELS), levels=LEVELS, draws=2
    )


def _loaded_personas(tmp_path: Path) -> dict:
    """A fake pools dir on disk, read back through the SAME loader the
    existing runs use (so the pool file format is pinned end to end)."""
    pools_dir = tmp_path / "pools"
    write_pools_dir(pools_dir, PRODUCTS)
    return sweep_cli._load_personas_by_product(pools_dir, PRODUCTS, 60)


def _read_leg_records(run_dir: Path) -> list[dict]:
    """Every record of every leg under the run dir, leg directory attached."""
    records = []
    safe_model = sweep_cli._safe_model_name(harness.DEFAULT_MODEL)
    model_dir = run_dir / safe_model
    assert model_dir.is_dir(), f"leg dirs must live under {model_dir}"
    for leg_dir in sorted(model_dir.iterdir()):
        jsonl = leg_dir / "records.jsonl"
        assert jsonl.exists(), f"{leg_dir} must hold a durable records.jsonl"
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                record["_leg_dir"] = leg_dir.name
                records.append(record)
    return records


# ---------------------------------------------------------------------------
# (1) Prompt parity through run_plan with a fake transport (the core)
# ---------------------------------------------------------------------------


def test_none_leg_requests_byte_match_the_sweep_kit_builders(monkeypatch, tmp_path):
    """Every none-leg request carries the exact blinded/unblinded system
    prompt and the exact Prompt-2 survey at the _price_for_level price, at
    the local sweep's temperature 1.0 - proven with sockets refused."""
    forbid_sockets(monkeypatch, "the offline harness run must not dial out")
    for blinding in ("blinded", "unblinded"):
        transport = FakeTransport(contents=['{"decision": "purchase"}'])
        harness.run_plan(
            _plan_for("none", blinding),
            PRODUCTS,
            None,
            tmp_path / f"none-{blinding}",
            transport,
            concurrency=1,
        )
        expected_system = (
            sweep_kit.build_blinded_system_prompt()
            if blinding == "blinded"
            else sweep_kit.build_unblinded_system_prompt(expected_design(blinding, "none"))
        )
        assert len(transport.payloads) == 8
        for payload in transport.payloads:
            assert payload["model"] == harness.DEFAULT_MODEL
            assert payload["response_format"] == EXACT_RESPONSE_FORMAT
            assert payload["temperature"] == 1.0
            [system, user] = payload["messages"]
            assert system["role"] == "system" and user["role"] == "user"
            assert system["content"] == expected_system, (
                f"system prompt must byte-equal the sweep_kit {blinding} builder"
            )
        sent_users = [p["messages"][1]["content"] for p in transport.payloads]
        assert sorted(sent_users) == sorted(expected_none_users() * 2), (
            "user prompts must byte-equal build_purchase_user_prompt at "
            "_price_for_level prices, each cell drawn twice"
        )


def test_demographics_leg_requests_byte_match_the_persona_path(monkeypatch, tmp_path):
    """Every demographics-leg request embeds one of the four subsampled pool
    personas exactly as _persona_user_prompt renders it, at the persona
    sweep's temperature 0.0 - proven with sockets refused."""
    forbid_sockets(monkeypatch, "the offline harness run must not dial out")
    personas_by_product = _loaded_personas(tmp_path)
    for blinding in ("blinded", "unblinded"):
        transport = FakeTransport(contents=['{"decision": "not purchase"}'])
        harness.run_plan(
            _plan_for("demographics", blinding),
            PRODUCTS,
            personas_by_product,
            tmp_path / f"demo-{blinding}",
            transport,
            concurrency=1,
        )
        expected_system = (
            sweep_kit.build_blinded_system_prompt()
            if blinding == "blinded"
            else sweep_kit.build_unblinded_system_prompt(
                expected_design(blinding, "demographics")
            )
        )
        assert len(transport.payloads) == 16
        for payload in transport.payloads:
            assert payload["model"] == harness.DEFAULT_MODEL
            assert payload["response_format"] == EXACT_RESPONSE_FORMAT
            assert payload["temperature"] == 0.0
            [system, user] = payload["messages"]
            assert system["role"] == "system" and user["role"] == "user"
            assert system["content"] == expected_system
        sent_users = [p["messages"][1]["content"] for p in transport.payloads]
        assert sorted(sent_users) == sorted(expected_persona_users()), (
            "persona user prompts must byte-equal the _persona_user_prompt "
            "rendering of pool personas 40, 46, 52 and 58"
        )


# ---------------------------------------------------------------------------
# (2)+(3) Records, durability layout and resume
# ---------------------------------------------------------------------------


def test_run_writes_self_describing_records_in_the_run_dir_layout(
    monkeypatch, tmp_path
):
    """A full offline mini run appends one self-describing record per call to
    each leg's records.jsonl under R1-API-QWEN38MAX-<ts>/<model-safe>/, with
    manifest.json and progress.json beside them; unclassified answers are
    recorded, never dropped."""
    forbid_sockets(monkeypatch, "the offline harness run must not dial out")
    personas_by_product = _loaded_personas(tmp_path)
    contents = ['{"decision": "purchase"}', '{"decision": "not purchase"}', "oops no json"]
    transport = FakeTransport(contents=contents)
    run_dir = tmp_path / "results" / "unblinding" / "R1-API-QWEN38MAX-20260915T000000"
    harness.run_plan(
        _full_mini_plan(),
        PRODUCTS,
        personas_by_product,
        run_dir,
        transport,
        concurrency=1,
    )
    plan = _full_mini_plan()
    records = _read_leg_records(run_dir)
    assert len(records) == plan["sweep_calls"] == 48
    unclassified = [r for r in records if r.get("unclassified")]
    assert unclassified, "the unparsable answer must be recorded as unclassified"
    for record in unclassified:
        assert record["parsed_purchase"] is None and record["decision"] is None
    parsed = {r["parsed_purchase"] for r in records}
    assert True in parsed and False in parsed, "both decisions must be mapped"
    for record in records:
        assert record["model"] == harness.DEFAULT_MODEL
        assert record["condition"] == record["_leg_dir"]
        assert record["product"] in {p["product"] for p in PRODUCTS}
        assert record["treatment_value"] in LEVELS
        regular = next(
            p["regular_price"] for p in PRODUCTS if p["product"] == record["product"]
        )
        assert record["price"] == sweep_kit._price_for_level(
            regular, record["treatment_value"]
        )
        assert record["raw_content"] in contents
        assert record["usage"]["prompt_tokens"] == 120
        assert record["cost_usd"] == pytest.approx(harness.call_cost_usd(record["usage"]))
        datetime.fromisoformat(record["timestamp"])
        if record["condition"].startswith("none"):
            assert record["persona_index"] is None
        else:
            assert record["persona_index"] in (40, 46, 52, 58)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "R1-API-QWEN38MAX"
    assert manifest["model"] == harness.DEFAULT_MODEL
    assert manifest["seed"] == 42
    progress = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
    assert progress["calls_done"] == 48 and progress["calls_total"] == 48
    assert progress["cost_usd"] == pytest.approx(sum(r["cost_usd"] for r in records))


def test_none_and_demographics_legs_carry_draw_and_persona_indices(
    monkeypatch, tmp_path
):
    """None legs stamp draw_index 0..draws-1 per cell with no persona; the
    demographics legs stamp draw_index 0..3 aligned with the persona order
    (40, 46, 52, 58)."""
    forbid_sockets(monkeypatch, "the offline harness run must not dial out")
    personas_by_product = _loaded_personas(tmp_path)
    transport = FakeTransport(contents=['{"decision": "purchase"}'])
    run_dir = tmp_path / "run"
    harness.run_plan(
        _full_mini_plan(),
        PRODUCTS,
        personas_by_product,
        run_dir,
        transport,
        concurrency=1,
    )
    by_leg: dict[str, list[dict]] = {}
    for record in _read_leg_records(run_dir):
        by_leg.setdefault(record["condition"], []).append(record)
    cells: dict[tuple, list[int]] = {}
    for record in by_leg["none_blinded"]:
        cells.setdefault((record["product"], record["treatment_value"]), []).append(
            record["draw_index"]
        )
    for draw_indices in cells.values():
        assert sorted(draw_indices) == [0, 1]
    demo_cells: dict[tuple, list[tuple]] = {}
    for record in by_leg["demographics_blinded"]:
        demo_cells.setdefault((record["product"], record["treatment_value"]), []).append(
            (record["draw_index"], record["persona_index"])
        )
    for pairs in demo_cells.values():
        pairs_sorted = sorted(pairs)
        assert [draw for draw, _persona in pairs_sorted] == [0, 1, 2, 3]
        assert [persona for _draw, persona in pairs_sorted] == [40, 46, 52, 58]


def test_resume_skips_cells_already_durable_on_disk(monkeypatch, tmp_path):
    """A second run_plan over a finished run dir makes zero calls; after one
    leg loses its last record, only that one cell is re-run and the leg is
    whole again."""
    forbid_sockets(monkeypatch, "the offline harness run must not dial out")
    personas_by_product = _loaded_personas(tmp_path)
    run_dir = tmp_path / "run"
    harness.run_plan(
        _full_mini_plan(),
        PRODUCTS,
        personas_by_product,
        run_dir,
        FakeTransport(contents=['{"decision": "purchase"}']),
        concurrency=1,
    )
    resumed = FakeTransport(contents=['{"decision": "purchase"}'])
    harness.run_plan(
        _full_mini_plan(),
        PRODUCTS,
        personas_by_product,
        run_dir,
        resumed,
        concurrency=1,
    )
    assert len(resumed.payloads) == 0, "a finished run must resume as a no-op"
    safe_model = sweep_cli._safe_model_name(harness.DEFAULT_MODEL)
    leg_jsonl = run_dir / safe_model / "none_blinded" / "records.jsonl"
    lines = leg_jsonl.read_text(encoding="utf-8").splitlines()
    leg_jsonl.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    repair = FakeTransport(contents=['{"decision": "purchase"}'])
    harness.run_plan(
        _full_mini_plan(),
        PRODUCTS,
        personas_by_product,
        run_dir,
        repair,
        concurrency=1,
    )
    assert len(repair.payloads) == 1, "only the missing cell may be re-run"
    restored = [line for line in leg_jsonl.read_text().splitlines() if line]
    assert len(restored) == 8


# ---------------------------------------------------------------------------
# (4) Cost guard
# ---------------------------------------------------------------------------


def test_run_hard_aborts_before_exceeding_max_cost(monkeypatch, tmp_path):
    """When the accumulated cost crosses --max-cost the run aborts with a
    clear cost error and stops calling the API immediately."""
    forbid_sockets(monkeypatch, "the offline harness run must not dial out")
    transport = FakeTransport(contents=['{"decision": "purchase"}'])
    real_call = transport.__call__

    def big_usage(payload: dict) -> dict:
        response = real_call(payload)
        response["usage"] = {
            "prompt_tokens": 2_000_000,
            "completion_tokens": 1_000_000,
        }
        return response

    with pytest.raises(RuntimeError, match="cost"):
        harness.run_plan(
            _plan_for("none", "blinded"),
            PRODUCTS,
            None,
            tmp_path / "run",
            big_usage,
            max_cost_usd=0.01,
            concurrency=1,
        )
    assert len(transport.payloads) == 1, "no calls may follow the cost breach"


# ---------------------------------------------------------------------------
# (5) Offline CLI: dry-run plan, missing-key fast fail, no key leakage
# ---------------------------------------------------------------------------


def test_dry_run_prints_the_plan_and_never_touches_the_network(monkeypatch, capsys):
    """--dry-run prints the profile, the pinned model, the 7,040-call
    geometry and a cost estimate, with every socket refused and no API key
    present at all."""
    forbid_sockets(monkeypatch, "the dry run must not contact anything")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    code = harness.main(["--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "R1-API-QWEN38MAX" in out
    assert "qwen/qwen3.8-max-0902" in out
    assert "7,040" in out
    assert "cost" in out.lower() and "$" in out


def test_run_without_api_key_fails_fast_without_dialing(monkeypatch, capsys):
    """A real run without OPENROUTER_API_KEY fails fast naming the variable,
    before any socket is opened."""
    forbid_sockets(monkeypatch, "a keyless run must not dial out")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        harness.main([])
    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert "OPENROUTER_API_KEY" in captured.out + captured.err


def test_api_key_never_appears_in_any_run_artifact(monkeypatch, tmp_path):
    """With a (fake) key in the environment, a full offline run leaves the
    key string nowhere - not in records, manifest, progress or any file."""
    forbid_sockets(monkeypatch, "the offline harness run must not dial out")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-LEAKME-123456789")
    personas_by_product = _loaded_personas(tmp_path)
    run_dir = tmp_path / "run"
    harness.run_plan(
        _full_mini_plan(),
        PRODUCTS,
        personas_by_product,
        run_dir,
        FakeTransport(contents=['{"decision": "purchase"}']),
        concurrency=1,
    )
    for path in run_dir.rglob("*"):
        if path.is_file():
            assert "sk-or-test-LEAKME-123456789" not in path.read_text(
                encoding="utf-8", errors="replace"
            ), f"the API key leaked into {path}"
