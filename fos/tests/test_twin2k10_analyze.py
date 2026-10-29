# Locked tests for the twin2k10 study's analysis module (TASK-2351 RED
# phase; tests ONLY — no implementation lives here yet).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The loader reads every model folder's records.jsonl under a run
#     directory and handles BOTH record shapes: a choice record (p_raw
#     keyed by answer letters like "A"/"B") and a digit record
#     (digit_items[], each carrying its own p_raw keyed by digit labels).
#   - distributions_long.csv is one row per (record item x answer label):
#     model, experiment, arm, blinding, persona, qid, row, label, prob.
#     Only folded answer labels appear — the model's other top-k tokens
#     never become rows. The extra "row" column (empty for choice items,
#     the digit item's row number otherwise) keeps multi-row questions
#     (linda, prob_matching, false_consensus) distinguishable — a
#     documented amendment to the TASK-2351 column list.
#   - arm_distributions.csv averages each label's probability over
#     personas, per (model, experiment, arm, blinding, qid, row, label).
#   - contrasts.csv uses the SAME contrast names as the shipped human
#     benchmarks file, with directions read off the names (X_minus_Y means
#     arm-X statistic minus arm-Y statistic). Each experiment's arm
#     statistic is pinned below (expected rating for likert scales,
#     expected digit for first-digit estimates, option/Yes probability for
#     2-option choices, mean label-1 share for prob_matching, the critical
#     statement's expected rating for linda).
#   - unblinding_effects.csv: effect = unblinded MINUS blinded contrast,
#     with a percentile bootstrap CI over personas (1000 resamples,
#     seed 42 — deterministic).
#   - human_comparison.csv aligns the LLM label probabilities to the human
#     benchmark codes: the n-th answer letter maps to human code "n";
#     digit labels already are the human codes.
#   - write_analysis_outputs writes all CSVs plus summary.json into --out,
#     and never writes into the run directory.
#
# All offline: pure functions over synthetic tmp_path run fixtures; the
# 57,000-record production run is never read.
import json
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import analyze, experiments  # noqa: E402

_BENCHMARKS = Path(
    "/home/justin/work/research/TWIN2K-UNBLIND-10TASKS/"
    "human_benchmark/benchmarks.json"
)


# ---------------------------------------------------------------- helpers

def _choice_record(model, persona_id, exp_name, arm, blind, qid,
                   p_raw, label_map=None):
    """One synthetic choice record (letter-probability shape)."""
    return {
        "model": model,
        "model_id": f"org/{model}",
        "persona_id": persona_id,
        "experiment": exp_name,
        "arm": arm,
        "blind": blind,
        "qids": [qid],
        "qid": qid,
        "choice_qid": qid,
        "p_raw": dict(p_raw),
        "p_norm": dict(p_raw),
        "label_map": label_map or {},
        "branch_mass": sum(v for v in p_raw.values() if v is not None),
        "low_branch_mass": False,
        "digit_items": [],
    }


def _digit_record(model, persona_id, exp_name, arm, blind, qid,
                  digit_p_raws, row=1):
    """One synthetic digit record (digit_items shape); one item here.

    p_raw dicts may contain None values (production records store null
    for digit labels absent from the model's top-k); the stored
    branch_mass sums only the real numeric probs, matching production.
    """
    items = [{
        "qid": qid,
        "row": row,
        "p_raw": dict(p),
        "p_norm": dict(p),
        "branch_mass": sum(v for v in p.values() if v is not None),
        "low_branch_mass": False,
    } for p in digit_p_raws]
    return {
        "model": model,
        "model_id": f"org/{model}",
        "persona_id": persona_id,
        "experiment": exp_name,
        "arm": arm,
        "blind": blind,
        "qids": [qid],
        "qid": qid,
        "p_raw": {},
        "label_map": {},
        "branch_mass": items[0]["branch_mass"],
        "low_branch_mass": False,
        "digit_items": items,
    }


def _write_run(root: Path, model: str, cell: str, records: list[dict]) -> Path:
    """Lay out a mini run dir: run_dir/model/cell/records.jsonl."""
    cell_dir = root / model / cell
    cell_dir.mkdir(parents=True)
    with open(cell_dir / "records.jsonl", "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return root


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Read a tidy CSV as (header, row-dict list)."""
    import csv
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def _expected_rating(label_probs: dict[str, float]) -> float:
    """Σ rank·prob for letter labels, where A is rank 1 (helper)."""
    return sum(
        (ord(label) - ord("A") + 1) * prob
        for label, prob in label_probs.items()
    )


def _expected_digit(label_probs: dict[str, float]) -> float:
    """Σ digit·prob over digit-string labels (helper)."""
    return sum(int(label) * prob for label, prob in label_probs.items())


# ----------------------------------------------------------------- loader

def test_load_records_reads_every_model_cell_under_run_dir(tmp_path):
    """All */records.jsonl files are loaded, one dict per line."""
    _write_run(tmp_path, "m1", "allais_blinded",
               [_choice_record("m1", 0, "allais", "form1", "blinded",
                               "QID192", {"A": 0.6, "B": 0.4})])
    _write_run(tmp_path, "m2", "linda_unblinded",
               [_choice_record("m2", 1, "linda", "conjunction", "unblinded",
                               "QID160", {"A": 0.1, "B": 0.9}),
               _choice_record("m2", 2, "linda", "conjunction", "unblinded",
                               "QID160", {"A": 0.3, "B": 0.7})])
    records = analyze.load_records(tmp_path)
    assert len(records) == 3
    assert {r["model"] for r in records} == {"m1", "m2"}


def test_load_records_handles_choice_and_digit_schemas(tmp_path):
    """Both record shapes load: choice p_raw and digit_items p_raw."""
    _write_run(tmp_path, "m1", "allais_blinded",
               [_choice_record("m1", 0, "allais", "form1", "blinded",
                               "QID192", {"A": 0.6, "B": 0.4})])
    _write_run(tmp_path, "m2", "linda_blinded",
               [_digit_record("m2", 0, "linda", "conjunction", "blinded",
                              "QID160",
                              [{"1": 0.1, "2": 0.2, "3": 0.3, "4": 0.2,
                                "5": 0.1, "6": 0.1}], row=1),
               _digit_record("m2", 0, "linda", "conjunction", "blinded",
                              "QID160",
                              [{"1": 0.2, "2": 0.2, "3": 0.2, "4": 0.2,
                                "5": 0.1, "6": 0.1}], row=2)])
    records = analyze.load_records(tmp_path)
    assert len(records) == 2
    digit = [r for r in records if r["digit_items"]][0]
    assert digit["digit_items"][0]["p_raw"]["3"] == pytest.approx(0.3)


def test_load_records_skips_dirs_without_records_jsonl(tmp_path):
    """Sub-directories without records.jsonl (pools, scratch) are skipped."""
    _write_run(tmp_path, "m1", "allais_blinded",
               [_choice_record("m1", 0, "allais", "form1", "blinded",
                               "QID192", {"A": 1.0, "B": 0.0})])
    (tmp_path / "pools").mkdir()
    (tmp_path / "m1" / "empty_cell").mkdir()
    assert len(analyze.load_records(tmp_path)) == 1


# ---------------------------------------------------- distributions_long

def test_distributions_long_columns_are_pinned(tmp_path):
    """Header: model, experiment, arm, blinding, persona, qid, row,
    label, prob (row is the documented TASK-2351 amendment)."""
    _write_run(tmp_path, "m1", "allais_blinded",
               [_choice_record("m1", 7, "allais", "form1", "blinded",
                               "QID192", {"A": 0.6, "B": 0.4})])
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    header, rows = _read_csv(out / "distributions_long.csv")
    assert header == ["model", "experiment", "arm", "blinding", "persona",
                      "qid", "row", "label", "prob"]
    assert len(rows) == 2  # two answer labels
    row_a = next(r for r in rows if r["label"] == "A")
    assert row_a["model"] == "m1"
    assert row_a["experiment"] == "allais"
    assert row_a["arm"] == "form1"
    assert row_a["blinding"] == "blinded"
    assert row_a["persona"] == "7"
    assert row_a["qid"] == "QID192"
    assert row_a["row"] == ""  # choice items carry no row
    assert float(row_a["prob"]) == pytest.approx(0.6)


def test_distributions_long_excludes_non_answer_labels(tmp_path):
    """Only folded answer labels become rows — a decoy junk token in
    top_logprobs (twin2k6 folding) never appears."""
    record = _choice_record("m1", 0, "allais", "form1", "blinded",
                            "QID192", {"A": 0.6, "B": 0.4})
    record["top_logprobs"] = [{"token": "We", "logprob": -5.0},
                              {"token": "**", "logprob": -6.0},
                              {"token": "A", "logprob": -0.5},
                              {"token": "B", "logprob": -0.9}]
    _write_run(tmp_path, "m1", "allais_blinded", [record])
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    _header, rows = _read_csv(out / "distributions_long.csv")
    assert {r["label"] for r in rows} == {"A", "B"}


def test_distributions_long_digit_items_use_digit_labels_and_row(tmp_path):
    """A digit item's labels are its p_raw digit strings, one row set per
    digit item; the row column disambiguates multi-row questions."""
    _write_run(tmp_path, "m1", "linda_blinded",
               [_digit_record("m1", 0, "linda", "conjunction", "blinded",
                              "QID160",
                              [{"1": 0.5, "2": 0.5}, {"1": 0.25, "2": 0.75}])])
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    _header, rows = _read_csv(out / "distributions_long.csv")
    assert len(rows) == 4  # 2 items x 2 labels
    row1 = {r["label"]: float(r["prob"])
            for r in rows if r["row"] == "1"}
    assert row1 == {"1": 0.5, "2": 0.5}


# ----------------------------------------------------- arm_distributions

def test_arm_distributions_average_labels_over_personas(tmp_path):
    """Each label's mean prob is the average across the arm's personas."""
    records = [
       _choice_record("m1", pid, "allais", "form1", "blinded", "QID192",
                       {"A": 0.6 + pid * 0.2, "B": 0.4 - pid * 0.2})
        for pid in range(2)
    ]
    _write_run(tmp_path, "m1", "allais_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    header, rows = _read_csv(out / "arm_distributions.csv")
    assert header == ["model", "experiment", "arm", "blinding", "qid",
                      "row", "label", "mean_prob"]
    got = {(r["arm"], r["label"]): float(r["mean_prob"]) for r in rows}
    assert got[("form1", "A")] == pytest.approx(0.7)
    assert got[("form1", "B")] == pytest.approx(0.3)


def test_long_csv_omits_none_prob_rows_from_digit_items(tmp_path):
    """A digit label absent from top-k is stored as a null prob; that
    label carries no information, so it must not become a CSV row."""
    _write_run(tmp_path, "m1", "linda_blinded",
               [_digit_record("m1", 0, "linda", "conjunction", "blinded",
                              "QID160",
                              [{"1": 0.6, "2": None, "3": 0.4}], row=1)])
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    _header, rows = _read_csv(out / "distributions_long.csv")
    assert len(rows) == 2  # labels "2" (None) is omitted
    assert {r["label"] for r in rows} == {"1", "3"}
    assert all(r["prob"] not in ("", "None") for r in rows)


def test_arm_distributions_compute_over_real_probs_only(tmp_path):
    """None probs never reach the mean: label "1" means 0.6 over two
    personas even though both records also carry a null entry."""
    records = [
        _digit_record("m1", pid, "linda", "conjunction", "blinded",
                      "QID160", [{"1": 0.6 + pid * 0.2, "2": None}],
                      row=1)
        for pid in range(2)
    ]
    _write_run(tmp_path, "m1", "linda_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    _header, rows = _read_csv(out / "arm_distributions.csv")
    got = {(r["row"], r["label"]): float(r["mean_prob"]) for r in rows}
    assert got[("1", "1")] == pytest.approx(0.7)
    assert ("1", "2") not in got  # the None label has no mean at all


def test_choice_records_with_none_probs_are_also_omitted(tmp_path):
    """Choice p_raw dicts can carry nulls too (real-data shape); the
    long CSV excludes them and arm means still compute."""
    records = [
        _choice_record("m1", pid, "allais", "form1", "blinded", "QID192",
                       {"A": 0.5 + pid * 0.2, "B": 0.2, "C": None})
        for pid in range(2)
    ]
    _write_run(tmp_path, "m1", "allais_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    _header, rows = _read_csv(out / "distributions_long.csv")
    assert {r["label"] for r in rows} == {"A", "B"}
    _header2, arm_rows = _read_csv(out / "arm_distributions.csv")
    got = {r["label"]: float(r["mean_prob"]) for r in arm_rows}
    assert got["A"] == pytest.approx(0.6)
    assert "C" not in got


def test_load_records_keeps_records_that_contain_none_probs(tmp_path):
    """Filtering drops the None-prob ROWS, never the whole record: the
    real probabilities in the same p_raw must survive the loader."""
    _write_run(tmp_path, "m1", "linda_blinded",
               [_digit_record("m1", 0, "linda", "conjunction", "blinded",
                              "QID160", [{"1": 0.6, "2": None}], row=1)])
    records = analyze.load_records(tmp_path)
    assert len(records) == 1
    assert records[0]["digit_items"][0]["p_raw"]["1"] == pytest.approx(0.6)


def test_arm_distributions_group_by_blinding_and_experiment(tmp_path):
    """Blinded and unblinded cells stay separate rows."""
    records = (
[        _choice_record("m1", 0, "allais", "form1", "blinded", "QID192",
                       {"A": 0.9, "B": 0.1})]
        + [_choice_record("m1", 0, "allais", "form1", "unblinded", "QID192",
                         {"A": 0.1, "B": 0.9})]
    )
    _write_run(tmp_path, "m1", "allais_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    _header, rows = _read_csv(out / "arm_distributions.csv")
    got = {(r["blinding"], r["label"]): float(r["mean_prob"]) for r in rows}
    assert got[("blinded", "A")] == pytest.approx(0.9)
    assert got[("unblinded", "A")] == pytest.approx(0.1)


def test_record_with_choice_and_digit_items_writes_arm_distributions(tmp_path):
    """Real anchoring records mix letter labels (choice p_raw) and digit
    labels (digit_items) in one record; writing the outputs must sort
    the mixed str/int keys deterministically, not crash with a
    '<' not supported between int and str TypeError."""
    record = _choice_record("m1", 0, "anchoring", "form1", "blinded",
                            "QID100", {"A": 0.7, "B": 0.3})
    record["digit_items"] = [{
        "qid": "QID100",
        "row": 1,
        # real digit records store integer labels 0-9, not strings
        "p_raw": {0: 0.5, 1: 0.3, 2: 0.2},
        "p_norm": {0: 0.5, 1: 0.3, 2: 0.2},
        "branch_mass": 1.0,
        "low_branch_mass": False,
    }]
    _write_run(tmp_path, "m1", "anchoring_blinded", [record])
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)  # must not raise
    header, rows = _read_csv(out / "arm_distributions.csv")
    assert header == ["model", "experiment", "arm", "blinding", "qid",
                      "row", "label", "mean_prob"]
    got = {(r["row"], r["label"]): float(r["mean_prob"]) for r in rows}
    assert got[("", "A")] == pytest.approx(0.7)
    assert got[("1", "0")] == pytest.approx(0.5)
    # deterministic order: rows sorted by str(key), letters before digits
    labels_in_order = [(r["row"], r["label"]) for r in rows]
    assert labels_in_order == sorted(labels_in_order)


# -------------------------------------------------------------- contrasts

def test_contrast_names_match_the_human_benchmarks_file():
    """Every pinned contrast name exists in the shipped wave1_3 data."""
    benchmarks = json.loads(_BENCHMARKS.read_text())
    humans = benchmarks["waves"]["wave1_3"]
    for exp_name in experiments.EXPERIMENTS:
        human_names = set(humans[exp_name]["contrasts"].keys())
        assert set(analyze.CONTRASTS[exp_name]) == human_names, exp_name


def test_contrast_directions_read_off_the_names():
    """X_minus_Y = stat(X) - stat(Y); worked values on synthetic arms."""
    model = "m1"
    records = (
        # allais: form1 p(A)=0.8, form2 p(A)=0.3 -> +0.5
[        _choice_record(model, 0, "allais", "form1", "blinded", "QID192",
                       {"A": 0.8, "B": 0.2})]
        + [_choice_record(model, 0, "allais", "form2", "blinded", "QID193",
                         {"A": 0.3, "B": 0.7})]
        # linda: critical statement (row 3) expected rating
        # conj: E=4.0 ; no_conj: E=2.0 -> +2.0
        + [_digit_record(model, 0, "linda", "conjunction", "blinded",
                         "QID160", [{"1": 0.0, "2": 0.0, "3": 0.0, "4": 1.0,
                                     "5": 0.0, "6": 0.0}], row=3)]
        + [_digit_record(model, 0, "linda", "no_conjunction", "blinded",
                         "QID159", [{"1": 1.0, "2": 0.0, "3": 0.0, "4": 0.0,
                                     "5": 0.0, "6": 0.0}], row=3)]
        # anchoring_redwood: expected first digit high 8 - low 3 -> +5.0
        + [_digit_record(model, 0, "anchoring_redwood", "high", "blinded",
                         "QID170", [{"8": 1.0, "9": 0.0}])]
        + [_digit_record(model, 0, "anchoring_redwood", "low", "blinded",
                         "QID168", [{"3": 1.0, "9": 0.0}])]
        # prob_matching: mean label-1 share p1 0.8 - p2 0.3 -> +0.5
        + [_digit_record(model, 0, "prob_matching", "problem1", "blinded",
                         "QID198", [{"1": 0.8, "2": 0.2}, {"1": 0.8,
                                                          "2": 0.2}])]
        + [_digit_record(model, 0, "prob_matching", "problem2", "blinded",
                         "QID203", [{"1": 0.3, "2": 0.7}, {"1": 0.3,
                                                          "2": 0.7}])]
    )
    contrasts = analyze.contrast_values(records)
    by_key = contrasts[(model, "allais", "blinded")]
    assert by_key["p_opt1_form1_minus_form2"] == pytest.approx(0.5)
    assert contrasts[(model, "linda", "blinded")][
        "critical_mean_conj_minus_noconj"] == pytest.approx(3.0)
    assert contrasts[(model, "anchoring_redwood", "blinded")][
        "mean_high_minus_low"] == pytest.approx(5.0)
    assert contrasts[(model, "prob_matching", "blinded")][
        "mean_majority_share_problem1_minus_problem2"] == pytest.approx(0.5)


def test_choice_likert_expected_ratings_drive_myside_and_outcome_bias():
    """myside/outcome_bias: letter position (A=1) is the rating scale."""
    model = "m1"
    # myside: ford E[A]=1.0 ; german E=2.0 -> mean_german_minus_ford = 1.0
    records = (
[        _choice_record(model, 0, "myside", "ford", "unblinded", "QID194",
                       {"A": 1.0})]
        + [_choice_record(model, 0, "myside", "german", "unblinded", "QID195",
                         {"A": 0.0, "B": 1.0})]
        # outcome_bias: success E=3.0 ; failure E=1.0 -> +2.0
        + [_choice_record(model, 0, "outcome_bias", "success", "unblinded",
                         "QID161",
                         {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.0, "E": 0.0,
                          "F": 0.0, "G": 0.0})]
        + [_choice_record(model, 0, "outcome_bias", "failure", "unblinded",
                         "QID162",
                         {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0,
                          "F": 0.0, "G": 0.0})]
    )
    contrasts = analyze.contrast_values(records)
    assert contrasts[(model, "myside", "unblinded")][
        "mean_german_minus_ford"] == pytest.approx(1.0)
    assert contrasts[(model, "outcome_bias", "unblinded")][
        "mean_success_minus_failure"] == pytest.approx(2.0)


def test_base_rate_and_abs_relative_and_african_contrasts():
    """base_rate (expected digit), abs_relative (p_yes), anchoring_african."""
    model = "m1"
    records = (
[        _digit_record(model, 0, "base_rate", "30_engineers", "blinded",
                      "QID154", [{"2": 0.5, "7": 0.5}])]  # E = 4.5
        + [_digit_record(model, 0, "base_rate", "70_engineers", "blinded",
                        "QID156", [{"7": 1.0}])]            # E = 7.0
        + [_choice_record(model, 0, "abs_relative", "calculator", "blinded",
                         "QID183", {"A": 0.2, "B": 0.8})]
        + [_choice_record(model, 0, "abs_relative", "jacket", "blinded",
                         "QID184", {"A": 0.7, "B": 0.3})]
        + [_digit_record(model, 0, "anchoring_african", "high", "blinded",
                        "QID166", [{"9": 1.0}])]
        + [_digit_record(model, 0, "anchoring_african", "low", "blinded",
                        "QID164", [{"4": 1.0}])]
    )
    contrasts = analyze.contrast_values(records)
    assert contrasts[(model, "base_rate", "blinded")][
        "mean_70_minus_30"] == pytest.approx(2.5)
    assert contrasts[(model, "abs_relative", "blinded")][
        "p_yes_jacket_minus_calculator"] == pytest.approx(0.5)
    assert contrasts[(model, "anchoring_african", "blinded")][
        "mean_high_minus_low"] == pytest.approx(5.0)


def test_false_consensus_has_no_contrasts(tmp_path):
    """The within-subject experiment pins no contrasts."""
    assert analyze.CONTRASTS["false_consensus"] == {}


def test_contrasts_csv_columns_are_pinned(tmp_path):
    """contrasts.csv header and one worked row."""
    records = (
[        _choice_record("m1", 0, "allais", "form1", "blinded", "QID192",
                       {"A": 0.8, "B": 0.2})]
        + [_choice_record("m1", 0, "allais", "form2", "blinded", "QID193",
                         {"A": 0.3, "B": 0.7})]
    )
    _write_run(tmp_path, "m1", "allais_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    header, rows = _read_csv(out / "contrasts.csv")
    assert header == ["model", "experiment", "blinding", "contrast", "value"]
    row = next(r for r in rows if r["contrast"] == "p_opt1_form1_minus_form2")
    assert float(row["value"]) == pytest.approx(0.5)


# --------------------------------------------------- unblinding effects

def test_unblinding_effect_is_unblinded_minus_blinded(tmp_path):
    """Worked example: blinded +0.5, unblinded -0.2 -> effect -0.7."""
    model = "m1"
    records = (
[        _choice_record(model, 0, "allais", "form1", "blinded", "QID192",
                       {"A": 0.8, "B": 0.2})]
        + [_choice_record(model, 0, "allais", "form2", "blinded", "QID193",
                         {"A": 0.3, "B": 0.7})]
        + [_choice_record(model, 0, "allais", "form1", "unblinded", "QID192",
                         {"A": 0.3, "B": 0.7})]
        + [_choice_record(model, 0, "allais", "form2", "unblinded", "QID193",
                         {"A": 0.5, "B": 0.5})]
    )
    _write_run(tmp_path, "m1", "allais_blinded", records)
    effects = analyze.unblinding_effects(records)
    got = effects[(model, "allais", "p_opt1_form1_minus_form2")]
    assert got["effect"] == pytest.approx(-0.7)


def test_unblinding_effects_csv_has_bootstrap_ci_columns(tmp_path):
    """Columns pin the seeded 1000-resample percentile bootstrap."""
    model = "m1"
    records = (
[        _choice_record(model, pid, "allais", "form1", "blinded", "QID192",
                       {"A": 0.8, "B": 0.2})]
        + [_choice_record(model, pid, "allais", "form2", "blinded", "QID193",
                         {"A": 0.3, "B": 0.7})]
        + [_choice_record(model, pid, "allais", "form1", "unblinded",
                         "QID192", {"A": 0.9, "B": 0.1})]
        + [_choice_record(model, pid, "allais", "form2", "unblinded",
                         "QID193", {"A": 0.1, "B": 0.9})]
        for pid in range(30)
    )
    records = [record for group in records for record in group]
    _write_run(tmp_path, "m1", "allais_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    header, rows = _read_csv(out / "unblinding_effects.csv")
    assert header == ["model", "experiment", "contrast", "blinded",
                      "unblinded", "effect", "ci_low", "ci_high"]
    row = next(r for r in rows
               if r["contrast"] == "p_opt1_form1_minus_form2")
    assert float(row["blinded"]) == pytest.approx(0.5)
    assert float(row["unblinded"]) == pytest.approx(0.8)
    assert float(row["effect"]) == pytest.approx(0.3)
    # constant per-persona effects -> degenerate CI at the point estimate
    assert float(row["ci_low"]) == pytest.approx(0.3)
    assert float(row["ci_high"]) == pytest.approx(0.3)


def test_bootstrap_is_seeded_and_deterministic(tmp_path):
    """Same inputs -> byte-identical unblinding_effects.csv."""
    def build():
        built = [
[            _choice_record("m1", pid, "allais", "form1", "blinded",
                           "QID192", {"A": 0.5 + (pid % 3) * 0.1, "B": 0.2})]
            + [_choice_record("m1", pid, "allais", "form2", "blinded",
                             "QID193", {"A": 0.3, "B": 0.4})]
            + [_choice_record("m1", pid, "allais", "form1", "unblinded",
                             "QID192", {"A": 0.9, "B": 0.05})]
            + [_choice_record("m1", pid, "allais", "form2", "unblinded",
                             "QID193", {"A": 0.1 + (pid % 2) * 0.05,
                                        "B": 0.4})]
            for pid in range(25)
        ]
        return [record for group in built for record in group]

    first, second = tmp_path / "a", tmp_path / "b"
    analyze.write_analysis_outputs(_write_run(
        tmp_path / "run_a", "m1", "allais_blinded", build()),
        _BENCHMARKS, first)
    analyze.write_analysis_outputs(_write_run(
        tmp_path / "run_b", "m1", "allais_blinded", build()),
        _BENCHMARKS, second)
    assert (first / "unblinding_effects.csv").read_bytes() == (
        second / "unblinding_effects.csv").read_bytes()


# ------------------------------------------------------ human comparison

def test_human_comparison_aligns_letters_to_human_codes(tmp_path):
    """Choice letter n maps to human code str(n); digit labels match
    codes directly. Human numbers come from the shipped benchmarks."""
    benchmarks = json.loads(_BENCHMARKS.read_text())
    human_pct = benchmarks["waves"]["wave1_3"]["allais"]["arms"]["form1"][
        "dist"]["1"]["pct"]
    records = [_choice_record("m1", 0, "allais", "form1", "blinded",
                              "QID192", {"A": 0.6, "B": 0.4})]
    _write_run(tmp_path, "m1", "allais_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    header, rows = _read_csv(out / "human_comparison.csv")
    assert header == ["model", "experiment", "arm", "blinding", "code",
                      "llm_prob", "human_pct"]
    code1 = next(r for r in rows if r["code"] == "1")
    assert code1["experiment"] == "allais"
    assert code1["arm"] == "form1"
    assert float(code1["llm_prob"]) == pytest.approx(0.6)
    assert float(code1["human_pct"]) == pytest.approx(human_pct)


def test_human_comparison_digit_labels_are_their_own_codes(tmp_path):
    """base_rate digit labels 0..9 align to the human slider codes."""
    benchmarks = json.loads(_BENCHMARKS.read_text())
    humans = benchmarks["waves"]["wave1_3"]
    records = [_digit_record("m1", 0, "base_rate", "30_engineers",
                             "blinded", "QID154", [{"3": 1.0}])]
    _write_run(tmp_path, "m1", "base_rate_blinded", records)
    out = tmp_path / "out"
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    _header, rows = _read_csv(out / "human_comparison.csv")
    got = {r["code"]: float(r["llm_prob"]) for r in rows}
    assert got == {"3": 1.0}
    # every code row's human_pct matches the shipped dist (when present)
    for row in rows:
        dist = humans["base_rate"]["arms"]["30_engineers"].get(
            "dist", {}).get(row["code"])
        if dist:
            assert float(row["human_pct"]) == pytest.approx(dist["pct"])


# ------------------------------------------------- summary + write path

def test_summary_json_is_written_alongside_the_csvs(tmp_path):
    """summary.json exists with record count; all outputs go to --out."""
    records = [
       _choice_record("m1", 0, "allais", "form1", "blinded", "QID192",
                       {"A": 0.8, "B": 0.2}),
       _digit_record("m1", 0, "linda", "conjunction", "blinded", "QID160",
                      [{"1": 1.0}], row=1),
    ]
    _write_run(tmp_path, "m1", "allais_blinded", records)
    out = tmp_path / "out"
    summary = analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, out)
    on_disk = json.loads((out / "summary.json").read_text())
    assert on_disk == summary
    assert summary["records"] == 2
    for name in ("distributions_long.csv", "arm_distributions.csv",
                 "contrasts.csv", "unblinding_effects.csv",
                 "human_comparison.csv", "summary.json"):
        assert (out / name).exists(), name


def test_run_directory_is_never_written_to(tmp_path):
    """The analysis reads the run dir but leaves it byte-identical."""
    records = [_choice_record("m1", 0, "allais", "form1", "blinded",
                              "QID192", {"A": 0.8, "B": 0.2})]
    run = _write_run(tmp_path, "m1", "allais_blinded", records)
    before = {p.relative_to(tmp_path): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    analyze.write_analysis_outputs(tmp_path, _BENCHMARKS, tmp_path / "out")
    after = {p.relative_to(tmp_path): p.read_bytes()
             for p in tmp_path.rglob("*") if p.is_file()
             if "out" not in p.relative_to(tmp_path).parts}
    assert before == after
