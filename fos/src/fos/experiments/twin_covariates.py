"""Measured Twin-2K-500 covariate panel behind the Appendix E stages.

Gui & Toubia (2025) Web Appendix E adds measured covariates to the persona
profile in 12 cumulative stages (Table E.1): stage 1 is the 14 Prompt-12
demographics, then one behavioural or psychological score chunk per stage
(tightwad-spendthrift at 2, discount + present bias at 3, ..., the Big Five
at 12). Every measured score comes from the real Twin-2K-500 panel, never
from the language model. This module reads that panel, cleans it, resamples
whole respondent rows and computes empirical percentiles; the Prompt-12
renderer (render_stage_block plus the demographic label lists) lives in the
private sibling module twin_covariates_render and is re-exported here.

What each function and class does:
    load_panel(scores_dir, demos_numeric, demos_label)
                               - Read the three wave score files and the
                                 QID11-24 demographic CSVs into a Panel.
    Panel.stage_pool(stage)    - Respondents whose whole row is usable at a
                                 stage (every cumulative measure valid and
                                 all 14 demographics present), sorted.
    Panel.pool_report()        - Per stage 1..12: pool size, excluded count,
                                 and total respondent count.
    Panel.percentile(col, s)   - Empirical percentile (integer 1-99) of a
                                 score among the panel's valid cells.
    Panel.profile_for(rid)     - One respondent's whole row as a dict:
                                 respondent_id, the 14 demographic label
                                 texts, and every measured score.
    Panel.draw_profile(...)    - Deterministically resample one whole row of
                                 a stage's pool (seeded -> same profile).
    render_stage_block(...)    - Render one profile at one stage into the
                                 Prompt-12 text (see twin_covariates_render).
    _cell_value(column, raw)   - Parse one CSV cell or mark it invalid.

Invalid cell rules (documented in the tests): a cell is invalid when it is
not a finite number (e.g. the literal "no switch"), when |value| >= 1e12
(the ~2^52 discount-overflow markers), or when it falls outside the measure's
printed Prompt-12 scale. A respondent with any invalid cell among a stage's
cumulative measures - or with a missing demographic - leaves that stage's
pool. Percentiles rank only the valid cells of the whole panel.
"""

from __future__ import annotations

import bisect
import csv
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fos.experiments.twin_covariates_render import (
    DEMOGRAPHIC_DISPLAY_LABELS,
    DEMOGRAPHIC_KEYS,
    render_stage_block,
)
from fos.i18n import T

__all__ = [
    "DEMOGRAPHIC_DISPLAY_LABELS",
    "DEMOGRAPHIC_KEYS",
    "MEASURE_WAVE",
    "STAGE_ADDED_COLUMNS",
    "Panel",
    "load_panel",
    "render_stage_block",
]

# Which wave score file every measured column ships in (RESULT-1496 §3).
# Note "score_conscientiousness" is the wave-1 Big Five score, never the
# wave-2 0-8 decoy column of the same name (Prompt 12's "wave1 score
# conscientiousness").
MEASURE_WAVE: dict[str, str] = {
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

# The measured score column(s) each stage ADDS, in Table E.1 / Prompt 12
# order (stage 1 adds no measured column; it is the 14 demographics).
STAGE_ADDED_COLUMNS: dict[int, tuple[str, ...]] = {
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

# The demographic answer columns in the wave-1 response CSVs.
_DEMOGRAPHIC_QIDS = [f"QID{q}" for q in range(11, 25)]

# The cleaning bound for the documented ~2^52 discount-overflow artifacts
# (4503599627370495 >= 1e12; RESULT-1500 notes the tests pin exactly 1e12).
_OVERFLOW_BOUND = 1e12

# Printed Prompt-12 scale range per measure. Measures without an entry (the
# economic-preference rates) have no printed range, so no out-of-range check
# applies to them.
_SCALE_BOUNDS: dict[str, tuple[float, float]] = {
    "score_ST-TW": (4.0, 26.0),
    "score_finliteracy": (0.0, 8.0),
    "score_numeracy": (0.0, 8.0),
    "score_mentalaccounting": (0.0, 100.0),
    "score_maximization": (1.0, 5.0),
    "score_minimalism": (1.0, 5.0),
    "score_GREEN": (1.0, 5.0),
    "score_extraversion": (1.0, 5.0),
    "score_agreeableness": (1.0, 5.0),
    "score_conscientiousness": (1.0, 5.0),
    "score_openness": (1.0, 5.0),
    "score_neuroticism": (1.0, 5.0),
}

# Stages of the Table E.1 ladder.
_STAGE_MIN = 1
_STAGE_MAX = 12


def _read_demographic_texts(path: str | Path) -> dict[int, list[str]]:
    """Read the 14 QID11-24 label texts per pid from one CSV file.

    Returns {pid: [14 texts in QID order]}; a missing or blank label cell is
    stored as an empty string so the caller can treat that row as having an
    incomplete demographic profile.
    """
    texts: dict[int, list[str]] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pid_raw = row.get("pid", "")
            try:
                pid = int(pid_raw)
            except (TypeError, ValueError):
                continue
            texts[pid] = [
                str(row.get(qid, "") or "").strip() for qid in _DEMOGRAPHIC_QIDS
            ]
    return texts


def _read_score_values(path: str | Path) -> dict[int, dict[str, str]]:
    """Read one wave score CSV into {TWIN_ID: {column: raw cell text}}."""
    values: dict[int, dict[str, str]] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                twin_id = int(row["TWIN_ID"])
            except (TypeError, ValueError, KeyError):
                continue
            values[twin_id] = {
                key: value for key, value in row.items() if key != "TWIN_ID"
            }
    return values


def _cell_value(column: str, raw: str) -> float | None:
    """Parse one score cell into a float, or None when the cell is invalid.

    A cell is invalid when it does not parse to a finite number (the literal
    "no switch" and friends), when |value| >= 1e12 (the ~2^52 overflow
    markers in the discount column), or when it sits outside the measure's
    printed Prompt-12 scale.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    if abs(value) >= _OVERFLOW_BOUND:
        return None
    bounds = _SCALE_BOUNDS.get(column)
    if bounds is not None and not (bounds[0] <= value <= bounds[1]):
        return None
    return value


@dataclass
class Panel:
    """One cleaned Twin-2K-500 covariate panel.

    Holds every respondent's measured scores (a float per column, None where
    the cell is invalid) and their 14 demographic label texts, then answers
    stage-pool, percentile and whole-row profile questions. respondent_ids
    are the sorted respondents shared by the score and demographic files.
    """

    respondent_ids: list[int]
    scores: dict[int, dict[str, float | None]]
    demographics: dict[int, list[str]]
    _valid_cells: dict[str, list[float]] = field(init=False, repr=False)
    _pools: dict[int, list[int]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Precompute the valid cells per measure and every stage pool."""
        self._valid_cells = {
            column: sorted(
                score
                for row_scores in self.scores.values()
                for score in [row_scores.get(column)]
                if score is not None
            )
            for column in MEASURE_WAVE
        }
        self._pools = {
            stage: self._build_pool(stage)
            for stage in range(_STAGE_MIN, _STAGE_MAX + 1)
        }

    def _complete_demographics(self, respondent_id: int) -> bool:
        """True when the respondent's 14 demographic labels are all present."""
        texts = self.demographics.get(respondent_id)
        return (
            texts is not None
            and len(texts) == len(DEMOGRAPHIC_KEYS)
            and all(text for text in texts)
        )

    def _build_pool(self, stage: int) -> list[int]:
        """Respondents usable at one stage: complete demographics and every
        cumulative measured cell valid."""
        columns = [
            column for s in range(2, stage + 1) for column in STAGE_ADDED_COLUMNS[s]
        ]
        pool = []
        for respondent_id in self.respondent_ids:
            if not self._complete_demographics(respondent_id):
                continue
            row = self.scores.get(respondent_id)
            if row is None or any(row.get(column) is None for column in columns):
                continue
            pool.append(respondent_id)
        return pool

    def stage_pool(self, stage: int) -> list[int]:
        """Return the sorted respondent ids resamplable at one stage."""
        return list(self._pools[stage])

    def pool_report(self) -> dict[int, dict[str, int]]:
        """Report every stage 1..12: pool_size, excluded, n_respondents."""
        total = len(self.respondent_ids)
        return {
            stage: {
                "pool_size": len(self._pools[stage]),
                "excluded": total - len(self._pools[stage]),
                "n_respondents": total,
            }
            for stage in range(_STAGE_MIN, _STAGE_MAX + 1)
        }

    def percentile(self, column: str, score: float) -> int:
        """Return the empirical percentile (integer 1-99) of one score.

        The basis is every valid cell of that measure across the panel. The
        percentile uses the midpoint-rank formula pinned in the tests:
        pct = clamp(round(100 * (rank_avg - 1) / (n_valid - 1)), 1, 99) with
        rank_avg the tied group's average rank. With fewer than two valid
        cells the single score is reported at the top of the scale (99).
        """
        values = self._valid_cells.get(column, [])
        count = len(values)
        if count < 2:
            return 99
        target = float(score)
        below = bisect.bisect_left(values, target)
        equal = bisect.bisect_right(values, target) - below
        rank_average = below + (equal + 1) / 2.0
        percentile = round(100.0 * (rank_average - 1.0) / (count - 1.0))
        return max(1, min(99, percentile))

    def profile_for(self, respondent_id: int) -> dict[str, Any]:
        """Return one respondent's whole row as a profile dict.

        The profile keeps the row whole (joint dependence survives): the
        respondent_id, the 14 demographic label texts under their profile
        keys, every measured column as a float (None when the cell is
        invalid), and a nested "percentiles" map of the panel's integer
        percentile per measured column.
        """
        if respondent_id not in self.respondent_ids:
            raise ValueError(
                T(
                    "error.twin_covariates.respondent_not_in_panel",
                    respondent_id=respondent_id,
                )
            )
        row_scores = self.scores.get(respondent_id, {})
        texts = self.demographics.get(respondent_id, [""] * len(DEMOGRAPHIC_KEYS))
        profile: dict[str, Any] = {
            "respondent_id": respondent_id,
            **{
                key: texts[index] if index < len(texts) else ""
                for index, key in enumerate(DEMOGRAPHIC_KEYS)
            },
        }
        for column in MEASURE_WAVE:
            profile[column] = row_scores.get(column)
        profile["percentiles"] = {
            column: (self.percentile(column, value) if value is not None else None)
            for column, value in row_scores.items()
            if column in MEASURE_WAVE
        }
        return profile

    def draw_profile(self, stage: int, seed: int | None) -> dict[str, Any]:
        """Resample ONE whole respondent row of a stage's pool, deterministically.

        The same seed always draws the same respondent from the same stage's
        pool; the returned profile is that respondent's full row, so the
        joint dependence among their measures is preserved.
        """
        pool = self._pools[stage]
        if not pool:
            raise ValueError(T("error.twin_covariates.empty_stage_pool", stage=stage))
        rng = random.Random(seed)
        return self.profile_for(pool[rng.randrange(len(pool))])


def load_panel(
    scores_dir: str | Path,
    demographics_numeric_csv: str | Path,
    demographics_label_csv: str | Path,
) -> Panel:
    """Load the Twin-2K-500 covariate panel from its CSV files.

    scores_dir holds the "wave N scores.csv" files (key TWIN_ID);
    demographics_numeric_csv and demographics_label_csv are the wave-1
    QID11-24 response files (key pid). Only the label texts are rendered, so
    the numeric file only confirms who answered; respondents missing from a
    score wave or from either demographic file never join a stage pool. A
    missing wave file or a missing measured column raises loudly instead of
    loading a silently empty panel.
    """
    score_files = {
        name: _read_score_values(Path(scores_dir) / name)
        for name in sorted(set(MEASURE_WAVE.values()))
    }
    numeric_ids = set(_read_demographic_texts(demographics_numeric_csv))
    label_texts = _read_demographic_texts(demographics_label_csv)
    shared = set.intersection(*(set(values) for values in score_files.values()))
    respondent_ids = sorted(shared & numeric_ids & set(label_texts))
    scores: dict[int, dict[str, float | None]] = {}
    for respondent_id in respondent_ids:
        row: dict[str, float | None] = {}
        for column, wave_name in MEASURE_WAVE.items():
            raw = score_files[wave_name].get(respondent_id, {}).get(column)
            if raw is None:
                raise ValueError(
                    T(
                        "error.twin_covariates.score_cell_missing",
                        column=column,
                        respondent_id=respondent_id,
                        wave_name=wave_name,
                    )
                )
            row[column] = _cell_value(column, raw)
        scores[respondent_id] = row
    return Panel(
        respondent_ids=respondent_ids,
        scores=scores,
        demographics=label_texts,
    )
