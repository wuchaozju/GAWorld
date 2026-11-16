# Locked tests for the twin2k10 study's cell enumeration, record identity,
# and resume/durability contract (TASK-2139 RED phase; tests ONLY — no
# implementation lives yet, so every test here errors at collection until
# scripts/twin2k10/cells.py exists).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - One record is one (model, persona, experiment, arm, blinding) cell.
#     The grid follows twin2k6 semantics: 15 models x 100 personas (0-99)
#     x arms x 2 blinding arms. The 10 experiments have 19 arms together
#     (nine 2-arm experiments + false_consensus's single within-subject
#     arm), so the study holds 5,700 cells per model / 57,000 total.
#   - Enumeration is deterministic (same order every call, seed 42) and
#     every cell key is unique.
#   - TASK-2182 pivot: the grid totals are unchanged (one record per
#     arm), but every arm's items are now first-token items — a record
#     stores label/digit logprob distributions (digit_items) exactly like
#     its choice distributions, and NO sampling field exists anywhere.
#
# All offline: pure enumeration plus a temp file; no network, no models.
import json
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import cells, config, experiments  # noqa: E402

# Arms per experiment, straight from the study's own loaded stimuli.
_ARM_NAMES = {
    (entry["experiment"], entry["arm"])
    for entry in experiments.load_stimuli().values()
}
N_ARMS = len(_ARM_NAMES)                     # 19 = 9 x 2-arms + 1 single
PER_MODEL = config.PERSONA_COUNT * N_ARMS * len(config.BLINDINGS)   # 3,800
TOTAL = len(config.MODELS) * PER_MODEL       # 57,000


def _record_from(cell: tuple) -> dict:
    """Build a minimal record dict carrying one cell's identity (helper)."""
    model, persona_id, experiment, arm, blind = cell
    return {
        "model": model, "persona_id": persona_id, "experiment": experiment,
        "arm": arm, "blind": blind,
    }


def _counting_transport(calls: list) -> object:
    """A fake scoring transport that records every call (helper)."""

    def transport(cell: tuple) -> dict:
        calls.append(cell)
        return {"succeeded": True}

    return transport


def test_expected_totals_follow_from_the_stimuli_grid() -> None:
    """5,700 records per model, 57,000 total — derived from the stimuli."""
    assert cells.EXPECTED_RECORDS_PER_MODEL == PER_MODEL == 3800
    assert cells.EXPECTED_RECORDS_TOTAL == TOTAL == 57000
    assert N_ARMS == 19
    assert cells.EXPECTED_RECORDS_TOTAL == len(config.MODELS) * cells.EXPECTED_RECORDS_PER_MODEL


def test_enumeration_lists_all_cells_in_a_fixed_order() -> None:
    """enumerate_cells lists 57,000 cells and never changes between calls."""
    first = cells.enumerate_cells()
    assert len(first) == TOTAL
    assert first == cells.enumerate_cells()


def test_seed_42_is_the_study_design_seed() -> None:
    """Determinism is pinned by the shared seed: config.SEED == 42."""
    assert config.SEED == 42


def test_every_cell_key_is_unique() -> None:
    """No two cells share the same 5-part identity."""
    keys = [cells.record_key(cell) for cell in cells.enumerate_cells()]
    assert len(keys) == TOTAL
    assert len(set(keys)) == TOTAL


def test_cell_shape_is_model_persona_experiment_arm_blind() -> None:
    """A cell is a 5-tuple drawn from the study's own grid values."""
    cell = cells.enumerate_cells()[0]
    assert isinstance(cell, tuple) and len(cell) == 5
    model, persona_id, experiment, arm, blind = cell
    assert model in config.MODELS
    assert isinstance(persona_id, int) and 0 <= persona_id < 100
    assert experiment in experiments.EXPERIMENTS
    assert blind in ("blinded", "unblinded")


def test_grid_covers_every_experiment_arm_persona_and_blinding() -> None:
    """Every (experiment, arm) × 100 personas × 2 blinds × 15 models."""
    all_cells = cells.enumerate_cells()
    assert {c[1] for c in all_cells} == set(range(100))
    assert {c[4] for c in all_cells} == {"blinded", "unblinded"}
    assert {(c[2], c[3]) for c in all_cells} == _ARM_NAMES
    for exp_name in experiments.EXPERIMENTS:
        subset = [c for c in all_cells if c[2] == exp_name]
        arm_names = {arm for (experiment, arm) in _ARM_NAMES
                     if experiment == exp_name}
        assert len(subset) == 15 * 100 * len(arm_names) * 2, exp_name


def test_false_consensus_contributes_half_the_cells_of_a_two_arm_experiment() -> None:
    """19 arms: false_consensus (1 arm) = 3,000 cells, each 2-arm = 6,000."""
    all_cells = cells.enumerate_cells()
    fc = [c for c in all_cells if c[2] == "false_consensus"]
    allais = [c for c in all_cells if c[2] == "allais"]
    assert len(fc) == 15 * 100 * 1 * 2
    assert len(allais) == 15 * 100 * 2 * 2


def test_subset_enumeration_by_passing_just_one_model() -> None:
    """Asking for one model yields exactly that model's 3,800 cells."""
    subset = cells.enumerate_cells(models=[config.MODELS[0]])
    assert len(subset) == PER_MODEL
    assert {cell[0] for cell in subset} == {config.MODELS[0]}


def test_record_key_reads_cells_and_records_but_rejects_other_types() -> None:
    """record_key: cells pass through, records are read, junk raises."""
    cell = cells.enumerate_cells()[0]
    assert cells.record_key(cell) == cell
    assert cells.record_key(_record_from(cell)) == cell
    with pytest.raises(TypeError):
        cells.record_key("not a cell")


def test_resume_skips_cells_already_on_disk() -> None:
    """A rerun calls the transport only for cells not yet in records.jsonl."""
    import tempfile
    all_cells = cells.enumerate_cells(models=[config.MODELS[0]],
                                      personas=[0, 1],
                                      experiments_map={
                                          "allais":
                                              experiments.EXPERIMENTS["allais"]
                                      })
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "records.jsonl"
        calls: list = []
        cells.run_cells(all_cells, _counting_transport(calls), path)
        assert len(calls) == len(all_cells)
        calls.clear()
        cells.run_cells(all_cells, _counting_transport(calls), path)
        assert calls == []


def test_records_on_disk_carry_their_cell_identity() -> None:
    """Every written record is stamped with its 5 identity fields."""
    import tempfile
    planned = cells.enumerate_cells(models=[config.MODELS[0]],
                                    personas=[0],
                                    experiments_map={
                                        "allais":
                                            experiments.EXPERIMENTS["allais"]
                                    })
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "records.jsonl"
        cells.run_cells(planned, _counting_transport([]), path)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == len(planned)
        for cell, line in zip(planned, lines):
            record = json.loads(line)
            assert cells.record_key(record) == cells.record_key(cell)


# ---------------------------------------------------------------------------
# TASK-2182 design pivot — records store first-token digit distributions.
# One record is still one (model, persona, experiment, arm, blind) cell
# (57,000 unchanged), but a cell's numeric items are now measured with
# one deterministic first-token call EACH, and the record stores their
# label/digit logprob distributions exactly like its choice
# distributions: record["digit_items"], one entry per digit item in
# survey order. The K=20 sampling era — samples, parse failures,
# expected_rows — is gone from the record schema entirely.
# ---------------------------------------------------------------------------


def _entry(token: str, prob: float) -> dict:
    """Build one top-k entry {token, logprob} from a probability (helper)."""
    return {"token": token, "logprob": math.log(prob)}


def _arm_item_tokens(experiment: str, arm: str) -> list[str]:
    """The answer token each first-token call of an arm returns (helper)."""
    if experiment == "false_consensus":
        return [str((i % 5) + 1) for i in range(10)]
    if experiment == "linda":
        return ["1", "2", "3"]
    if experiment == "prob_matching":
        rows = 10 if arm == "problem1" else 6
        return [str((i % 2) + 1) for i in range(rows)]
    if experiment == "base_rate":
        return ["4"]
    if experiment == "anchoring_redwood" and arm == "low":
        return ["A", "7"]  # the anchor choice letter, then the digit
    return ["A"]


def _offline_first_token_record(experiment: str, arm: str,
                                fail_call: int | None = None) -> tuple:
    """One real cell's record with every fake call healthy (helper).

    The fake scorer answers each call with the arm's next answer token,
    so every stored distribution is attributable to exactly one item
    call. Returns (record, messages_of_each_call_in_order).
    """
    from twin2k10 import legexec

    context = legexec.LegContext(
        model=config.MODELS[0],
        model_id=f"offline-{config.MODELS[0]}",
        base_url="http://127.0.0.1:8080",
        personas=[{"persona_id": 0}],
        stimuli=experiments.load_stimuli(),
        inference=legexec.inference_settings("http://127.0.0.1:8080"),
    )
    tokens = iter(_arm_item_tokens(experiment, arm))
    calls: list[list] = []

    def fake_scorer(messages: list) -> dict:
        calls.append(messages)
        try:
            token = next(tokens)
        except StopIteration:
            raise AssertionError(
                f"unexpected extra scorer call #{len(calls)}"
            ) from None
        if fail_call is not None and len(calls) - 1 == fail_call:
            raise OSError("server gone mid-arm")
        return {"top_logprobs": [_entry(token, 0.9)],
                "decision_position": 0, "skipped_prefix": [],
                "skipped_len": 0, "succeeded": True}

    cell = (config.MODELS[0], 0, experiment, arm, "blinded")
    return legexec.execute_cell(context, fake_scorer, cell), calls


def test_every_item_of_every_arm_is_first_token_scored() -> None:
    """The grid's item mix is choice + digit only — nothing samples."""
    for experiment, spec in experiments.EXPERIMENTS.items():
        for arm, _qids in spec.arms:
            items = experiments.arm_items(experiment, arm)
            assert items and all(item["kind"] in ("choice", "digit")
                                 for item in items), (experiment, arm)


def test_false_consensus_record_stores_one_distribution_per_policy() -> None:
    """Ten single-policy calls land as ten 1–5 label distributions."""
    rows = experiments.load_stimuli()["QID287"]["rows"]
    record, calls = _offline_first_token_record("false_consensus", "all")
    items = record["digit_items"]
    assert len(items) == 10
    assert len(calls) == 10
    for number, item in enumerate(items, start=1):
        assert item["row"] == number
        assert item["qid"] == "QID287"
        assert item["statement"] == rows[number - 1]
        assert set(item["p_raw"]) == {"1", "2", "3", "4", "5"}
        found = str((number - 1) % 5 + 1)
        assert item["p_raw"][found] == pytest.approx(0.9), number
        assert item["branch_mass"] == pytest.approx(0.9)


def test_each_fc_call_sees_only_its_own_policy_statement() -> None:
    """Every rating call is asked ONE policy — never the other nine."""
    rows = experiments.load_stimuli()["QID287"]["rows"]
    _record, calls = _offline_first_token_record("false_consensus", "all")
    for number, messages in enumerate(calls):
        user = messages[-1]["content"]
        assert rows[number] in user, number
        for other in rows[:number] + rows[number + 1:]:
            assert other not in user, (number, other)


def test_digit_items_carry_their_own_prompt_and_hash() -> None:
    """Each digit item stamps its own prompt pair for audit parity."""
    from twin2k10 import legexec, prompts

    record, _calls = _offline_first_token_record("false_consensus", "all")
    for item in record["digit_items"]:
        assert item["user_prompt"]
        assert item["prompt_sha256"] == legexec.prompt_sha256(
            record["system_prompt"], item["user_prompt"]
        )
        assert prompts.NUMERIC_INSTRUCTION \
            in item["user_prompt"].split("\n\n")[-1]


def test_anchoring_record_stores_the_mc_item_plus_one_digit_item() -> None:
    """An anchoring record: letter distribution + one 0-9 digit item."""
    record, calls = _offline_first_token_record("anchoring_redwood", "low")
    assert len(calls) == 2
    assert set(record["p_raw"]) == {"A", "B"}          # the MC item
    digit_items = record["digit_items"]
    assert len(digit_items) == 1
    entry = digit_items[0]
    assert entry["qid"] == "QID168"
    assert entry["row"] is None and entry["statement"] is None
    assert set(entry["p_raw"]) == set("0123456789")
    assert entry["p_raw"]["7"] == pytest.approx(0.9)
    from twin2k10 import prompts
    # The digit call's prompt carries the estimate question verbatim, with the
    # arm's anchor choice question embedded above it (RESULT-2214 Fix 2: the
    # anchor context must reach the estimate call so low/high arms differ).
    # Amended per TASK-2217: the earlier "anchor must NOT appear" assertion was
    # pre-pivot and contradicts the locked TASK-2215 test
    # test_different_anchor_numbers_produce_different_digit_prompts.
    digit_user = calls[1][-1]["content"]
    assert "How tall do you think the tallest redwood tree" in digit_user
    assert "Is the tallest redwood tree in the world more or less than 85 feet tall?" in digit_user
    # The anchor's letter option lines must never render in the digit prompt.
    assert "A. more" not in digit_user
    assert "B. less" not in digit_user
    assert digit_user.split("\n\n")[-1].strip() == prompts.NUMERIC_INSTRUCTION.strip()


def test_base_rate_record_uses_the_first_significant_digit_labels() -> None:
    """A numeric question's record: one digit item, labels 0-9, no choice."""
    record, calls = _offline_first_token_record("base_rate", "30_engineers")
    assert len(calls) == 1
    assert "choice_qid" not in record
    entry = record["digit_items"][0]
    assert set(entry["p_raw"]) == set("0123456789")
    assert entry["p_raw"]["4"] == pytest.approx(0.9)


def test_linda_record_stores_three_six_point_distributions() -> None:
    """Linda's three statements land as three 1–6 label distributions."""
    record, _calls = _offline_first_token_record("linda", "conjunction")
    items = record["digit_items"]
    assert len(items) == 3
    for number, item in enumerate(items, start=1):
        assert set(item["p_raw"]) == {"1", "2", "3", "4", "5", "6"}
        assert item["p_raw"][str(number)] == pytest.approx(0.9)


def test_records_carry_no_sampling_fields() -> None:
    """The sampling-era record fields are gone from the schema entirely."""
    record, _calls = _offline_first_token_record("false_consensus", "all")
    banned = [key for key in record
              if key.startswith("numeric_") or key.startswith("multi_numeric_")]
    assert banned == []
    for field in ("expected_rows", "parse_failures", "calls_failed"):
        assert field not in record, field


def test_choice_top_logprobs_win_the_record_audit_field() -> None:
    """An anchoring record's canonical top-k is still the MC call's."""
    record, _calls = _offline_first_token_record("anchoring_redwood", "low")
    assert record["top_logprobs"] == [_entry("A", 0.9)]


def test_record_top_logprobs_fall_back_to_the_first_digit_item() -> None:
    """A digit-only arm audits its first item's top-k (GGUF check lives)."""
    record, _calls = _offline_first_token_record("false_consensus", "all")
    assert record["top_logprobs"] == record["digit_items"][0]["top_logprobs"]


def test_a_failed_item_call_blocks_record_success() -> None:
    """One failing first-token call fails the record — never a silent row."""
    record, _calls = _offline_first_token_record("false_consensus", "all",
                                                 fail_call=3)
    assert record["succeeded"] is False
    assert record["error"]
    assert record["digit_items"][3]["succeeded"] is False
