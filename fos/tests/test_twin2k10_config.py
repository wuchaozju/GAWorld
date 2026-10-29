# Locked tests for the twin2k10 study's configuration module (TASK-2139 RED
# phase; tests ONLY — no implementation lives yet, so every test here errors
# at collection until scripts/twin2k10/config.py exists).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The study runs the exact same 15 local models as the proven twin2k6
#     study, in the same order.
#   - The grid knobs match twin2k6: two blinding arms, 100 personas, design
#     seed 42, the R1 inference knobs, the 0.80 branch-mass flag, and the
#     at-most-50-records fsync promise.
#   - twin2k10's own knobs: the run-name prefixes, the smoke-test model,
#     and (since the TASK-2182 design pivot) NO sampling knobs — every
#     numeric answer is one deterministic first-token call, so the old
#     K=20 temperature-sampling constants are deleted.
#   - The 23 survey questions (10 experiments) are shipped inside this repo
#     and are a verbatim copy of the authoritative research delivery.
#
# All offline: file reads and pure asserts; no network, no model loads.
import json
import sys
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import config, legexec, scoring  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent

# The authoritative research delivery this study's questions must match.
# Read-only source of truth; the repo ships its own verbatim copy.
AUTHORITATIVE_STIMULI = Path(
    "/home/justin/work/research/TWIN2K-UNBLIND-10TASKS/human_benchmark/stimuli.json"
)


def _load_authoritative() -> list[dict]:
    """The 23 authoritative stimulus entries, in file order (helper)."""
    with open(AUTHORITATIVE_STIMULI, encoding="utf-8") as handle:
        return json.load(handle)


def _load_shipped_entries() -> list[dict]:
    """The repo's shipped stimulus entries, wrapper-agnostic (helper).

    Accepts either a bare list of entries or a dict carrying them under a
    "stimuli" key — same two shapes the research delivery uses.
    """
    with open(config.STIMULI_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return data["stimuli"]
    return data


def test_model_list_is_exactly_twin2k6s_15_models_in_the_same_order() -> None:
    """twin2k10 reuses twin2k6's pinned 15-model queue, byte for byte."""
    from twin2k6 import config as k6_config

    assert list(config.MODELS) == list(k6_config.MODELS)
    assert len(set(config.MODELS)) == 15


def test_grid_constants_mirror_twin2k6() -> None:
    """Blinding arms, persona pool, seed and inference knobs equal twin2k6."""
    from twin2k6 import config as k6_config

    assert config.BLINDINGS == ("blinded", "unblinded")
    assert config.BLINDINGS == k6_config.BLINDINGS
    assert config.PERSONA_COUNT == 100
    assert config.SEED == 42
    assert config.SCAN_TOKENS == k6_config.SCAN_TOKENS
    assert config.TEMPERATURE == k6_config.TEMPERATURE
    assert config.TOP_K >= 100
    assert config.PROBABILITY_FLOOR == k6_config.PROBABILITY_FLOOR
    assert config.LOW_BRANCH_MASS_THRESHOLD == k6_config.LOW_BRANCH_MASS_THRESHOLD
    assert config.FSYNC_EVERY == 50
    assert config.DEFAULT_BASE_URL == k6_config.DEFAULT_BASE_URL
    assert config.DEFAULT_MANAGER_URL == k6_config.DEFAULT_MANAGER_URL


def test_numeric_answers_are_one_deterministic_first_token_call() -> None:
    """TASK-2182 pivot: no multi-day K multiplier, no sampling knobs.

    The K=20 temperature-sampling constants are DELETED, not deprecated:
    every numeric answer is measured with one deterministic first-token
    call, so there is nothing left to configure about sampling.
    """
    assert not hasattr(config, "NUMERIC_SAMPLES_K")
    assert not hasattr(config, "NUMERIC_MAX_TOKENS")


def test_run_names_start_with_the_T2K10_prefix() -> None:
    """Run folders can never collide with twin2k6 runs."""
    from twin2k6 import config as k6_config

    assert config.RUN_NAME_PREFIX == "T2K10-"
    assert config.STUDY_NAME != k6_config.STUDY_NAME


def test_stimuli_file_is_shipped_inside_this_repo() -> None:
    """The study never depends on a machine-specific research path."""
    assert config.STIMULI_PATH.is_file(), config.STIMULI_PATH
    assert config.REPO_ROOT in config.STIMULI_PATH.resolve().parents


def test_shipped_stimuli_are_a_verbatim_copy_of_the_research_delivery() -> None:
    """All 23 shipped entries equal the authoritative file, entry by entry."""
    authoritative = {entry["qid"]: entry for entry in _load_authoritative()}
    shipped = {entry["qid"]: entry for entry in _load_shipped_entries()}
    assert len(_load_shipped_entries()) == 23
    assert shipped == authoritative


def test_shipped_stimuli_cover_10_experiments_and_23_questions() -> None:
    """The shipped catalogue holds the 10 study experiments, 23 qids."""
    experiments = {entry["experiment"] for entry in _load_shipped_entries()}
    assert len(_load_shipped_entries()) == 23
    assert experiments == {
        "allais", "linda", "base_rate", "anchoring_redwood",
        "anchoring_african", "outcome_bias", "myside", "prob_matching",
        "abs_relative", "false_consensus",
    }


# --------------------------------------------------------------------------
# TASK-2182 RED tests — the design pivot DELETES the sampling machinery:
# no sampler module, no multi-row free-text parser, no sampler wiring in
# the executor, and no sampling knobs on the record inference stamp.
# Every numeric record stores label/digit logprob distributions exactly
# like a choice record.
# --------------------------------------------------------------------------


def test_the_sampler_module_is_deleted() -> None:
    """twin2k10.numerics (the K-sample machinery) no longer exists."""
    import importlib.util

    assert importlib.util.find_spec("twin2k10.numerics") is None, (
        "the temperature-sampling module must be deleted with the pivot"
    )


def test_the_multi_row_free_text_parser_is_deleted() -> None:
    """parse_multi_numeric parsed sampled text; there are no samples left."""
    assert not hasattr(scoring, "parse_multi_numeric")


def test_the_executor_has_no_sampler_parameter_left() -> None:
    """execute_cell / make_transport never take (or build) a sampler."""
    import inspect

    assert "sampler" not in inspect.signature(legexec.execute_cell).parameters
    assert "sampler" not in \
        inspect.signature(legexec.make_transport).parameters
    assert not hasattr(legexec, "numerics"), (
        "the executor must no longer import the sampler module"
    )


def test_inference_stamp_has_no_sampling_knobs() -> None:
    """The pinned inference settings on records carry no numeric knobs."""
    settings = legexec.inference_settings("http://127.0.0.1:8080")
    sampling_keys = [key for key in settings if "numeric" in key]
    assert sampling_keys == []
