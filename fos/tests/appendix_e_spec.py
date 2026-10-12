# Shared spec + fixture for the TASK-1500 RED tests (Appendix E measured-
# covariate stage machinery, Gui & Toubia 2025 Table E.1 / Prompt 12).
# This module is LOCKED like the test files: it holds the ground-truth
# constants the tests pin (Table E.1 counts, per-stage measured columns and
# their wave files, Prompt 12's demographic labels) and the writer that lays
# an eight-row synthetic Twin-2K-500 panel into tmp_path. It is not a test
# module (no test_ prefix) so pytest never collects it.
#
# Ground truth comes from:
#   RESULT-1474 §1 (Prompt 12 verbatim) and §3.1.3 (Table E.1) - the paper.
#   RESULT-1496 §3 - which measured score column lives in which wave file of
#       the Twin-2K-500 raw_data, the score scales, the "no switch" /
#       ~2^52-overflow artefacts, and the QID11-24 demographic mapping.
#   RESULT-1483 - the depth-1/2 contract ({none, demographics}) that the
#       stage ladder extends and must not change.

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

# Table E.1 (RESULT-1474 §3.1.3): cumulative covariate count per stage.
TABLE_E1_COUNTS = {
    1: 14,
    2: 15,
    3: 17,
    4: 18,
    5: 19,
    6: 20,
    7: 21,
    8: 22,
    9: 23,
    10: 24,
    11: 25,
    12: 30,
}

# The measured score column each stage ADDS, in Prompt 12 / Table E.1 order:
# stage 2 tightwad-spendthrift, 3 discount + present bias, 4 risk aversion,
# 5 loss aversion, 6 financial literacy, 7 numeracy, 8 mental accounting,
# 9 maximization, 10 minimalism, 11 GREEN, 12 the Big Five (wave-1
# conscientiousness per Prompt 12's "wave1 score conscientiousness").
STAGE_ADDED_COLUMNS = {
    2: ("score_ST-TW",),
    3: ("score_discount", "score_presentbias"),
    4: ("score_riskaversion",),
    5: ("score_lossaversion",),
    6: ("score_finliteracy",),
    7: ("score_numeracy",),
    8: ("score_mentalaccounting",),
    9: ("score_maximization",),
    10: ("score_minimalism",),
    11: ("score_GREEN",),
    12: (
        "score_extraversion",
        "score_agreeableness",
        "score_conscientiousness",
        "score_openness",
        "score_neuroticism",
    ),
}

# The score file each measured column ships in (RESULT-1496 §3).
MEASURE_WAVE = {
    "score_ST-TW": "wave 3 scores.csv",
    "score_discount": "wave 2 scores.csv",
    "score_presentbias": "wave 2 scores.csv",
    "score_riskaversion": "wave 2 scores.csv",
    "score_lossaversion": "wave 2 scores.csv",
    "score_finliteracy": "wave 2 scores.csv",
    "score_numeracy": "wave 2 scores.csv",
    "score_mentalaccounting": "wave 1 scores.csv",
    "score_maximization": "wave 3 scores.csv",
    "score_minimalism": "wave 1 scores.csv",
    "score_GREEN": "wave 1 scores.csv",
    "score_extraversion": "wave 1 scores.csv",
    "score_agreeableness": "wave 1 scores.csv",
    "score_conscientiousness": "wave 1 scores.csv",
    "score_openness": "wave 1 scores.csv",
    "score_neuroticism": "wave 1 scores.csv",
}

# Prompt 12's "# Demographics:" block - 14 bullet display labels verbatim.
DEMOGRAPHIC_DISPLAY_LABELS = [
    "Geographic region",
    "Gender",
    "Age",
    "Education level",
    "Race",
    "Citizen of the US",
    "Marital status",
    "Religion",
    "Religious attendance",
    "Political affiliation",
    "Income",
    "Political views",
    "Household size",
    "Employment status",
]

# The eight synthetic respondents: id -> per-measure csv cell strings. 105
# has a literal "no switch" discount, 106 a literal "no switch" loss
# aversion, 107 a ~2^52 overflow-marker discount (4503599627370495), 108 a
# mental-accounting score outside the documented 0-100 range. Big Five
# tuples are (extraversion, agreeableness, conscientiousness_wave1, openness,
# neuroticism).
FIXTURE_ROWS = {
    101: dict(
        st="7",
        disc="0.05",
        pb="0.10",
        risk="0.20",
        loss="1.5",
        fl="6",
        num="7",
        ma="40",
        mx="3.0",
        mn="2.0",
        gr="3",
        bf=("2.125", "4.0", "4.0", "3.5", "1.5"),
    ),
    102: dict(
        st="12",
        disc="0.15",
        pb="0.20",
        risk="0.40",
        loss="2.5",
        fl="7",
        num="8",
        ma="50",
        mx="3.5",
        mn="3.0",
        gr="4",
        bf=("2.5", "3.0", "4.5", "2.0", "2.0"),
    ),
    103: dict(
        st="18",
        disc="0.25",
        pb="0.30",
        risk="0.60",
        loss="3.5",
        fl="4",
        num="5",
        ma="60",
        mx="4.0",
        mn="4.0",
        gr="2",
        bf=("3.0", "5.0", "3.0", "4.0", "3.0"),
    ),
    104: dict(
        st="24",
        disc="0.35",
        pb="0.40",
        risk="0.80",
        loss="4.5",
        fl="8",
        num="4",
        ma="70",
        mx="4.5",
        mn="5.0",
        gr="5",
        bf=("3.5", "2.0", "5.0", "1.0", "4.0"),
    ),
    105: dict(
        st="7",
        disc="no switch",
        pb="0.50",
        risk="0.20",
        loss="1.5",
        fl="5",
        num="6",
        ma="80",
        mx="3.0",
        mn="2.0",
        gr="3",
        bf=("2.125", "4.0", "4.0", "3.5", "1.5"),
    ),
    106: dict(
        st="12",
        disc="0.45",
        pb="0.60",
        risk="0.40",
        loss="no switch",
        fl="6",
        num="7",
        ma="90",
        mx="3.5",
        mn="3.0",
        gr="4",
        bf=("2.5", "3.0", "4.5", "2.0", "2.0"),
    ),
    107: dict(
        st="18",
        disc="4503599627370495.0",
        pb="0.70",
        risk="0.60",
        loss="3.5",
        fl="4",
        num="5",
        ma="100",
        mx="4.0",
        mn="4.0",
        gr="2",
        bf=("3.0", "5.0", "3.0", "4.0", "3.0"),
    ),
    108: dict(
        st="12",
        disc="0.55",
        pb="0.80",
        risk="0.80",
        loss="4.5",
        fl="8",
        num="4",
        ma="150",
        mx="4.5",
        mn="5.0",
        gr="5",
        bf=("3.5", "2.0", "5.0", "1.0", "4.0"),
    ),
}

# The resampling pool each stage must report for the fixture: respondents
# whose every needed measure is valid AND whose 14 demographics are complete
# (row 105 is missing its employment-status demographic).
FIXTURE_EXPECTED_POOLS = {
    1: [101, 102, 103, 104, 106, 107, 108],
    2: [101, 102, 103, 104, 106, 107, 108],
    3: [101, 102, 103, 104, 106, 108],
    4: [101, 102, 103, 104, 106, 108],
    5: [101, 102, 103, 104, 108],
    6: [101, 102, 103, 104, 108],
    7: [101, 102, 103, 104, 108],
    8: [101, 102, 103, 104],
    9: [101, 102, 103, 104],
    10: [101, 102, 103, 104],
    11: [101, 102, 103, 104],
    12: [101, 102, 103, 104],
}

# The wave-2 0-8 conscientiousness decoy values that must never be used.
_WAVE2_CONSCIENTIOUSNESS_DECOY = {
    "101": "8",
    "102": "7",
    "103": "6",
    "104": "5",
    "105": "8",
    "106": "7",
    "107": "6",
    "108": "5",
}

# Realistic demographic label texts for respondent 103 (canonical render pin).
_REAL_DEMOS_103 = [
    "South (TX, OK, AR, LA, MS, AL, GA, FL, TN, KY, WV, VA, NC, SC)",
    "Male",
    "30-49",
    "Bachelor's degree",
    "White",
    "Yes",
    "Married",
    "Catholic",
    "Once a week",
    "Democrat",
    "$75,000-$100,000",
    "Liberal",
    "3",
    "Full-time employment",
]


def _require_module(name: str):
    """Import a module or fail this test because the feature is missing."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        pytest.fail(f"appendix E machinery: module {name} does not exist yet ({exc})")


def _require_attr(obj, name: str):
    """Read an attribute or fail this test because the feature is missing."""
    if not hasattr(obj, name):
        pytest.fail(
            f"appendix E machinery: {obj.__name__}.{name} is not implemented yet"
        )
    return getattr(obj, name)


def load_script(path: Path, name: str):
    """Import a repo script by path without opening any socket."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"no loader for {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module.__name__, None)
    return module


def write_fixture_panel(root: Path) -> tuple[Path, Path, Path]:
    """Lay the eight-row synthetic Twin-2K-500 panel into root; return
    (scores_dir, demographics numeric csv, demographics label csv)."""
    scores_dir = root / "scores"
    scores_dir.mkdir(parents=True, exist_ok=True)
    w1_cols = [
        "score_extraversion",
        "score_agreeableness",
        "score_conscientiousness",
        "score_openness",
        "score_neuroticism",
        "score_minimalism",
        "score_GREEN",
        "score_mentalaccounting",
    ]
    w2_cols = [
        "score_discount",
        "score_presentbias",
        "score_riskaversion",
        "score_lossaversion",
        "score_finliteracy",
        "score_numeracy",
        "score_conscientiousness",
    ]  # last: 0-8 decoy, never used
    w3_cols = ["score_ST-TW", "score_maximization"]
    with (scores_dir / "wave 1 scores.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["TWIN_ID", *w1_cols, "filler"])
        writer.writeheader()
        for rid, row in FIXTURE_ROWS.items():
            body = dict(zip(w1_cols[0:5], row["bf"]))
            body["score_minimalism"] = row["mn"]
            body["score_GREEN"] = row["gr"]
            body["score_mentalaccounting"] = row["ma"]
            writer.writerow({"TWIN_ID": rid, **body, "filler": "x"})
    with (scores_dir / "wave 2 scores.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["TWIN_ID", *w2_cols, "filler"])
        writer.writeheader()
        for rid, row in FIXTURE_ROWS.items():
            writer.writerow(
                {
                    "TWIN_ID": rid,
                    "score_discount": row["disc"],
                    "score_presentbias": row["pb"],
                    "score_riskaversion": row["risk"],
                    "score_lossaversion": row["loss"],
                    "score_finliteracy": row["fl"],
                    "score_numeracy": row["num"],
                    "score_conscientiousness": _WAVE2_CONSCIENTIOUSNESS_DECOY[str(rid)],
                    "filler": "x",
                }
            )
    with (scores_dir / "wave 3 scores.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["TWIN_ID", *w3_cols, "filler"])
        writer.writeheader()
        for rid, row in FIXTURE_ROWS.items():
            writer.writerow(
                {
                    "TWIN_ID": rid,
                    "score_ST-TW": row["st"],
                    "score_maximization": row["mx"],
                    "filler": "x",
                }
            )
    numeric_path = root / "demos_numeric.csv"
    label_path = root / "demos_label.csv"
    qids = [f"QID{i}" for i in range(11, 25)]
    texts: dict[int, list[str]] = {}
    for rid in FIXTURE_ROWS:
        texts[rid] = (
            [f"demo-{rid}-{label}" for label in DEMOGRAPHIC_DISPLAY_LABELS]
            if rid != 103
            else list(_REAL_DEMOS_103)
        )
    texts[105][-1] = ""  # row 105 is missing its employment-status label
    with numeric_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pid", *qids])
        writer.writeheader()
        for rid in sorted(FIXTURE_ROWS):
            writer.writerow({"pid": rid, **{qid: (rid % 5) + 1 for qid in qids}})
    with label_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pid", *qids])
        writer.writeheader()
        for rid in sorted(FIXTURE_ROWS):
            writer.writerow({"pid": rid, **dict(zip(qids, texts[rid]))})
    return scores_dir, numeric_path, label_path


def fixture_panel(tmp_path: Path):
    """Load the fixture panel through the loader; RED when it is missing."""
    twin = _require_module("fos.experiments.twin_covariates")
    load_panel = _require_attr(twin, "load_panel")
    return load_panel(*write_fixture_panel(tmp_path))
