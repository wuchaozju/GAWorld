# Locked tests for the twin2k10 LLM ARM-MEANS builder (TASK-2395 RED
# phase; tests ONLY — the implementation in
# scripts/twin2k10/llm_arm_means.py does not exist yet, so every test
# below must fail on the missing feature, never on a typo here).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The builder reads run records from the run directories named in
#     the registry (synthetic copies written under tmp_path — no real
#     run directory is ever touched) and computes, for each model and
#     experiment, the MEAN RAW-SCALE outcome per arm, separately for
#     the blinded and unblinded legs, plus how many records each mean
#     is based on.
#   - Each experiment's raw outcome comes from its registry
#     record_to_outcome_map.llm rule:
#       * disease (run6 letters): the record's ready-made p_safe_norm
#         field (first-token mass on letters A-C = the safe option).
#       * allais: P(option 1) = the record's p_norm mass on letter "A"
#         (A is always option 1 in both forms).
#       * linda: the expected digit from the critical statement's
#         first-token digit mass, using only digits 1-6 (digit 0 is
#         off-scale noise and is dropped, with the rest renormalised).
#       * prob_matching: per trial, P(majority deck) = mass on "1"
#         divided by the trial's total digit mass; the record's share
#         is the mean over its trials; the leg mean is the mean over
#         records.
#       * base_rate: the registry rule is NEEDS-OWNER, so the arm mean
#         is None (null in the written JSON) even though n is counted.
#   - Records that did not succeed (succeeded: false) are excluded
#     from both the mean and n.
#   - Reconciliation: where the registry stores a pooled per-blinding
#     mean (both arms lumped together), the pooled value must equal
#     the arm means averaged with arm-n as weights — this is how a
#     reviewer can check the builder against the registry numbers.
#   - Output shape (figures contract):
#       {model: {experiment: {"blinded":   {"means": {arm: float},
#                                            "n":     {arm: int}},
#                             "unblinded": {...}}}}
import json
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import llm_arm_means  # noqa: E402

MODEL = "gpt-oss-20b"


# --------------------------------------------------------------- fixtures
def _write_records(root: Path, model: str, leg: str, experiment: str,
                   records: list[dict]) -> None:
    """Write one synthetic records.jsonl leg in the real schema."""
    leg_dir = root / model / leg
    leg_dir.mkdir(parents=True, exist_ok=True)
    with open(leg_dir / "records.jsonl", "w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _letter_record(experiment: str, arm: str, p_norm: dict,
                   extra: dict | None = None) -> dict:
    """A choice record over letters (allais shape) or with a
    precomputed safe-mass field (disease shape)."""
    rec = {
        "model_id": f"openai/{MODEL}",
        "model": MODEL,
        "experiment": experiment,
        "arm": arm,
        "blind": "blinded",
        "succeeded": True,
        "p_norm": p_norm,
    }
    if extra:
        rec.update(extra)
    return rec


def _linda_record(arm: str, row3_p_norm: dict) -> dict:
    """A linda record: three statement rows, row 3 is the critical one
    whose digit mass (tokens "0"-"6") carries the answer."""
    def item(row: int, p_norm: dict) -> dict:
        return {"qid": f"QID160", "row": row, "p_norm": p_norm,
                "succeeded": True}
    return {
        "model_id": f"openai/{MODEL}", "model": MODEL,
        "experiment": "linda", "arm": arm, "blind": "blinded",
        "succeeded": True, "qid": "QID160", "qids": ["QID160"],
        "digit_items": [item(1, {"1": 1.0}), item(2, {"2": 1.0}),
                        item(3, row3_p_norm)],
    }


def _prob_record(arm: str, trial_p_norms: list[dict]) -> dict:
    """A prob_matching record: one digit_items entry per trial."""
    return {
        "model_id": f"openai/{MODEL}", "model": MODEL,
        "experiment": "prob_matching", "arm": arm, "blind": "blinded",
        "succeeded": True, "qid": "QID198", "qids": ["QID198"],
        "digit_items": [
            {"qid": "QID198", "row": i + 1, "p_norm": p}
            for i, p in enumerate(trial_p_norms)
        ],
    }


@pytest.fixture
def env(tmp_path):
    """Synthetic run roots + a registry subset covering one experiment
    of each reduction shape. Returns (registry, run_roots)."""
    root6 = tmp_path / "run6"
    root10 = tmp_path / "run10"

    # disease (run6): outcome read straight off the p_safe_norm field.
    _write_records(root6, MODEL, "disease_blinded", "disease", [
        _letter_record("disease", "gain", {}, {"p_safe_norm": 0.8}),
        _letter_record("disease", "gain", {}, {"p_safe_norm": 0.6}),
        _letter_record("disease", "loss", {}, {"p_safe_norm": 0.2}),
    ])
    _write_records(root6, MODEL, "unblinded", "disease", [
        _letter_record("disease", "gain", {}, {"p_safe_norm": 0.4}),
        _letter_record("disease", "loss", {}, {"p_safe_norm": 0.1}),
        _letter_record("disease", "loss", {}, {"p_safe_norm": 0.3}),
        # one failed record: must be excluded from mean AND n
        _letter_record("disease", "loss", {}, {"p_safe_norm": 0.9,
                                               "succeeded": False}),
    ])

    # allais (run10): P(option 1) = p_norm["A"].
    _write_records(root10, MODEL, "allais_blinded", "allais", [
        _letter_record("allais", "form1", {"A": 0.6, "B": 0.4}),
        _letter_record("allais", "form2", {"A": 0.2, "B": 0.8}),
    ])
    _write_records(root10, MODEL, "unblinded", "allais", [
        _letter_record("allais", "form1", {"A": 0.5, "B": 0.5}),
        _letter_record("allais", "form1", {"A": 0.9, "B": 0.1}),
        _letter_record("allais", "form2", {"A": 0.3, "B": 0.7}),
    ])

    # linda (run10): expected digit over 1-6 from the row-3 mass; the
    # 0.1 on digit "0" is off-scale noise and must be dropped.
    row3 = {"0": 0.1, "1": 0.2, "2": 0.2, "3": 0.2,
            "4": 0.1, "5": 0.2, "6": 0.1}
    _write_records(root10, MODEL, "linda_blinded", "linda", [
        _linda_record("conjunction", row3),
        _linda_record("no_conjunction", {"1": 1.0}),
    ])

    # prob_matching (run10): share of majority per record.
    _write_records(root10, MODEL, "prob_matching_blinded", "prob_matching",
                   [
                       _prob_record("problem1", [
                           {"1": 0.8, "2": 0.2}, {"1": 0.9, "2": 0.1}]),
                       _prob_record("problem2", [{"1": 1.0, "2": 0.0}]),
                   ])

    # base_rate (run10): NEEDS-OWNER — no derivable numeric estimate.
    _write_records(root10, MODEL, "base_rate_blinded", "base_rate", [
        _letter_record("base_rate", "30_engineers",
                       {"0": 0.5, "5": 0.5}),
    ])

    # Pooled per-blinding mean for allais blinded, as the real registry
    # stores it (both arms lumped): (1*0.6 + 1*0.2) / 2 = 0.4.
    registry = {
        "experiments": {
            "disease": {
                "run": "run6",
                "leg_path_pattern":
                    str(root6) + "/{model}/{disease_blinded,unblinded}"
                                 "/records.jsonl",
                "arm_roles": {"gain": "comparison", "loss": "treatment"},
                "record_to_outcome_map": {
                    "llm": "p_safe_norm (mass on A-C) = P(safe) directly"},
            },
            "allais": {
                "run": "run10",
                "leg_path_pattern":
                    str(root10) + "/{model}/{allais_blinded,unblinded}"
                                  "/records.jsonl",
                "arm_roles": {"form1": "comparison", "form2": "treatment"},
                "record_to_outcome_map": {
                    "llm": "P(option 1) = p_norm[\"A\"]"},
                "llm_arm_means": {
                    "models": {MODEL: {
                        "blinded": {"n_records": 2, "mean": 0.4},
                        "unblinded": {"n_records": 3, "mean": 0.4666667},
                    }}},
            },
            "linda": {
                "run": "run10",
                "leg_path_pattern":
                    str(root10) + "/{model}/{linda_blinded,unblinded}"
                                  "/records.jsonl",
                "arm_roles": {"conjunction": "treatment",
                              "no_conjunction": "comparison"},
                "record_to_outcome_map": {
                    "llm": "row==3 critical; expected digit from p_norm "
                           "restricted to 1-6; digit 0 mass is noise"},
            },
            "prob_matching": {
                "run": "run10",
                "leg_path_pattern":
                    str(root10) + "/{model}/{prob_matching_blinded,"
                                  "unblinded}/records.jsonl",
                "arm_roles": {"problem1": "arm", "problem2": "arm"},
                "record_to_outcome_map": {
                    "llm": "per trial P(majority) = p_norm[\"1\"] / "
                           "digit mass; share = mean over trials"},
            },
            "base_rate": {
                "run": "run10",
                "leg_path_pattern":
                    str(root10) + "/{model}/{base_rate_blinded,unblinded}"
                                  "/records.jsonl",
                "arm_roles": {"30_engineers": "comparison",
                              "70_engineers": "treatment"},
                "record_to_outcome_map": {
                    "llm": "NEEDS-OWNER: no derived expected-value field"},
            },
        }
    }
    run_roots = {"run6": root6, "run10": root10}
    return registry, run_roots


def _build(env):
    registry, run_roots = env
    return llm_arm_means.build_llm_arm_means(registry, run_roots)


# ------------------------------------------------------------------ tests
def test_builder_returns_arm_means_for_every_bliding_and_arm(env):
    """The output nests model -> experiment -> blinding -> arm means,
    with the hand-computed disease means in the right slots."""
    out = _build(env)
    disease = out[MODEL]["disease"]
    assert math.isclose(disease["blinded"]["means"]["gain"], 0.7)
    assert math.isclose(disease["blinded"]["means"]["loss"], 0.2)
    assert math.isclose(disease["unblinded"]["means"]["gain"], 0.4)
    assert math.isclose(disease["unblinded"]["means"]["loss"], 0.2)
    assert set(disease) == {"blinded", "unblinded"}


def test_builder_reports_n_per_arm(env):
    """Each arm also reports how many records its mean is based on."""
    out = _build(env)
    disease = out[MODEL]["disease"]
    assert disease["blinded"]["n"] == {"gain": 2, "loss": 1}
    assert disease["unblinded"]["n"] == {"gain": 1, "loss": 2}


def test_failed_records_are_excluded_from_mean_and_n(env):
    """A record with succeeded=false counts nowhere."""
    out = _build(env)
    disease = out[MODEL]["disease"]
    # without the failed record the loss leg has exactly 2 records
    assert disease["unblinded"]["n"]["loss"] == 2
    assert math.isclose(disease["unblinded"]["means"]["loss"], 0.2)


def test_allais_outcome_is_mass_on_option_one_letter(env):
    """allais: the outcome is p_norm['A'], letter A = option 1."""
    out = _build(env)
    allais = out[MODEL]["allais"]
    assert math.isclose(allais["blinded"]["means"]["form1"], 0.6)
    assert math.isclose(allais["blinded"]["means"]["form2"], 0.2)
    assert math.isclose(allais["unblinded"]["means"]["form1"], 0.7)


def test_linda_expected_digit_is_mass_weighted_restricted_to_1_to_6(env):
    """linda: expected digit from row-3 mass, digit 0 dropped and the
    1-6 mass renormalised (the 1-6 masses sum to 1.0): 3.2 / 1.0."""
    out = _build(env)
    linda = out[MODEL]["linda"]
    expected = (0.2 * 1 + 0.2 * 2 + 0.2 * 3 + 0.1 * 4
                + 0.2 * 5 + 0.1 * 6) / 1.0
    assert math.isclose(linda["blinded"]["means"]["conjunction"], expected)
    assert math.isclose(linda["blinded"]["means"]["no_conjunction"], 1.0)


def test_prob_matching_share_is_mean_over_trials_of_majority_mass(env):
    """prob_matching: per-trial P(majority)=p_norm['1']/digit mass,
    record share = mean over trials, leg mean = mean over records."""
    out = _build(env)
    prob = out[MODEL]["prob_matching"]
    assert math.isclose(prob["blinded"]["means"]["problem1"], 0.85)
    assert math.isclose(prob["blinded"]["means"]["problem2"], 1.0)


def test_base_rate_arm_mean_is_none_because_map_is_needs_owner(env):
    """base_rate: NEEDS-OWNER rule -> mean is None, n still counted."""
    out = _build(env)
    base = out[MODEL]["base_rate"]
    assert base["blinded"]["means"]["30_engineers"] is None
    assert base["blinded"]["n"]["30_engineers"] == 1


def test_pooled_registry_mean_reconciles_with_weighted_arm_means(env):
    """Cross-check: the registry's pooled per-blinding mean equals the
    arm means averaged with arm-n as weights."""
    registry, _ = env
    out = _build(env)
    allais = out[MODEL]["allais"]
    pooled = registry["experiments"]["allais"]["llm_arm_means"]\
        ["models"][MODEL]["blinded"]["mean"]
    n1 = allais["blinded"]["n"]["form1"]
    n2 = allais["blinded"]["n"]["form2"]
    m1 = allais["blinded"]["means"]["form1"]
    m2 = allais["blinded"]["means"]["form2"]
    weighted = (n1 * m1 + n2 * m2) / (n1 + n2)
    assert math.isclose(weighted, pooled, abs_tol=1e-6)
