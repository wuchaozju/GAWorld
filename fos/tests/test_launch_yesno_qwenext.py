# Locked tests for the R1-YESNO-QWENEXT profile (TASK-1627, RED phase;
# retry of the cancelled TASK-1625; tests ONLY - no implementation lives
# here).
#
# WHY THESE TESTS EXIST: R1-YESNO-QWENEXT re-runs the R1-YESNO logprob
# experiment with three additional Qwen models, each answering the SAME
# persona slice that qwen/qwen3.8-27b answered in R1-YESNO (pool personas
# [40, 60) of every product's 100-persona pool). All offline (no network,
# no model loads, no GPU): the queue spec is a pure specification, exactly
# like launch_queue.py. Locked here:
#   (1) PROFILE: the module names its run-level profile
#       QWENEXT_PROFILE = "R1-YESNO-QWENEXT" (the YESNO_PROFILE pattern).
#   (2) QUEUE: exactly three Qwen models in one fixed order; the ids are
#       the model manager's registry ids, character for character.
#   (3) SLICE: every model answers the same [40, 60) slice qwen3.8-27b
#       answered in R1-YESNO - a shared slice, not a partition - and an
#       index outside the 3-model queue is refused, never sliced empty.
#   (4) PLAN: 3 models x 4 legs (none/demographics x blinded/unblinded);
#       per model 880 bare + 17,600 demographics = 18,480 calls, 55,440
#       total; same 0-200% price levels, seed/pool conventions, LEG_FILE
#       and durability machinery as every existing profile.
#   (5) DEFAULTS: none of the three models appears in the queue's per-model
#       top-k or control-sequence override maps (top_k stays 20).
#   (6) NO SOCKET: importing the module never opens a socket.
#   (7) DRY RUN: a plan printer prints the whole plan offline (no manager,
#       no server), and never shows the purchase grammar.
#
# The locked offline tests in test_launch_queue.py, test_r1_yesno.py,
# test_logprob_profile.py and test_model_top_k.py stay green.
import importlib
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

# The module the contract names (suggested placement, following the
# launch_* convention in scripts/).
MODULE_NAME = "launch_yesno_qwenext"

# The R1-YESNO run geometry (results/unblinding/R1-YESNO-20260912T003134):
# 40 products, 11 price levels 0-200%, one scoring pass per prompt.
PRODUCTS_COUNT = 40
LEVELS = [float(x) for x in range(0, 220, 20)]

# The three Qwen models of the QWENEXT queue, in run order, exactly as the
# model manager's MODEL_REGISTRY names them (~/fos-model-manager).
QWENEXT_MODELS = (
    "qwen/qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive",
    "qwen3-4b",
)


def _qwenext_module():
    """The qwenext launcher module (import fails while it doesn't exist)."""
    return importlib.import_module(MODULE_NAME)


def _qwenext_plan():
    """The qwenext queue plan for the standard R1-YESNO design inputs."""
    module = _qwenext_module()
    return module.build_qwenext_plan(PRODUCTS_COUNT, len(LEVELS), levels=LEVELS)


def _forbid_socket(message: str):
    """A socket constructor stand-in that refuses every dial."""
    def _refuse(*_args, **_kwargs):
        raise AssertionError(message)

    return _refuse


# --- (1) Profile: the module carries its own profile id ------------------

def test_qwenext_module_defines_the_qwenext_profile_constant():
    """The module names its run-level profile R1-YESNO-QWENEXT, following
    the YESNO_PROFILE / LOGP_PROFILE naming pattern of the other queues."""
    module = _qwenext_module()
    assert module.QWENEXT_PROFILE == "R1-YESNO-QWENEXT", (
        f"the module must define QWENEXT_PROFILE='R1-YESNO-QWENEXT' (the "
        f"YESNO_PROFILE naming pattern); got "
        f"{getattr(module, 'QWENEXT_PROFILE', None)!r}"
    )


# --- (2) Queue: exactly the three Qwen models, in order ------------------

def test_qwenext_model_queue_is_exactly_the_three_qwen_models_in_order():
    """The queue runs exactly three Qwen models in one fixed order; every
    id must match the manager's registry character for character - a
    near-miss id would load the wrong model or none at all."""
    module = _qwenext_module()
    assert module.QWENEXT_MODEL_QUEUE == QWENEXT_MODELS, (
        f"QWENEXT_MODEL_QUEUE must be exactly (in order) {QWENEXT_MODELS}; "
        f"got {getattr(module, 'QWENEXT_MODEL_QUEUE', None)!r}"
    )


# --- (3) Slice: all three share qwen3.8-27b's R1-YESNO slice -------------

def test_every_qwenext_model_answers_the_same_slice_qwen3_8_27b_answered():
    """All three models answer pool personas [40, 60) of every product -
    the exact slice qwen/qwen3.8-27b (queue index 2) answered in R1-YESNO.
    The slices are shared by design, not a partition."""
    from launch_queue import MODEL_QUEUE, persona_slice

    assert MODEL_QUEUE[2] == "qwen/qwen3.8-27b", (
        "the contract anchors on qwen/qwen3.8-27b being queue index 2"
    )
    expected = persona_slice(2)
    assert expected == (40, 60), (
        f"qwen3.8-27b's R1-YESNO slice must be (40, 60); got {expected}"
    )
    module = _qwenext_module()
    for index in range(len(QWENEXT_MODELS)):
        assert module.qwenext_persona_slice(index) == expected, (
            f"qwenext model {index} must answer the SAME [40, 60) slice "
            f"qwen3.8-27b answered; got {module.qwenext_persona_slice(index)}"
        )


def test_qwenext_persona_slice_refuses_an_index_outside_the_queue():
    """An index outside the 3-model queue raises instead of silently
    slicing empty (the same never-guess convention as persona_slice)."""
    module = _qwenext_module()
    with pytest.raises(ValueError):
        module.qwenext_persona_slice(len(QWENEXT_MODELS))
    with pytest.raises(ValueError):
        module.qwenext_persona_slice(-1)


# --- (4) Plan: 3 x 4 legs, the R1-YESNO geometry, queue-leg durability ---

def test_qwenext_plan_stamps_its_own_profile_with_the_yesno_geometry():
    """The plan keeps the R1-YESNO geometry (one scoring pass per prompt:
    880 bare + 17,600 demographics = 18,480 calls per model, 12 legs,
    55,440 total) under the profile's OWN id - and building it never
    disturbs the other profiles' plans."""
    from launch_queue import (
        LOGP_NONE_DRAWS,
        PERSONAS_PER_MODEL,
        POOL_PERSONAS_PER_PRODUCT,
        build_logprob_plan,
    )
    assert LOGP_NONE_DRAWS == 1
    plan = _qwenext_plan()
    assert plan["profile"] == "R1-YESNO-QWENEXT", (
        f"the plan must be stamped R1-YESNO-QWENEXT, not a borrowed "
        f"{plan['profile']!r}"
    )
    assert plan["draws"] == 1, "one scoring pass per prompt, like R1-YESNO"
    assert len(plan["models"]) == 3
    assert len(plan["legs"]) == 12, f"3 models x 4 legs; got {len(plan['legs'])}"
    assert plan["k"] == POOL_PERSONAS_PER_PRODUCT == 100
    assert plan["per_model_personas"] == PERSONAS_PER_MODEL == 20
    assert plan["sweep_calls"] == 55_440, (
        f"3 models x 18,480 = 55,440; got {plan['sweep_calls']}"
    )
    for meta in plan["models"]:
        assert meta["model"] in QWENEXT_MODELS
        assert meta["none_calls"] == 880, (
            f"2 x 40 x 11 x 1 = 880 bare cells; got {meta['none_calls']}"
        )
        assert meta["demographics_calls"] == 17_600, (
            f"2 x 40 x 20 x 11 = 17,600 demographics cells; "
            f"got {meta['demographics_calls']}"
        )
        assert meta["total_calls"] == 18_480
        assert meta["persona_slice"] == [40, 60], (
            "every model's plan entry must self-describe the shared "
            f"[40, 60) slice; got {meta['persona_slice']}"
        )
    assert build_logprob_plan(40, 11, levels=LEVELS)["profile"] == "R1LP", (
        "building the qwenext plan must leave the plain R1LP plan untouched"
    )


def test_qwenext_plan_runs_the_four_standard_legs_per_model():
    """Per model, in order: none_blinded, none_unblinded,
    demographics_blinded, demographics_unblinded - 440 calls per none leg
    (40 x 11 x 1) and 8,800 per demographics leg (40 x 20 x 11)."""
    plan = _qwenext_plan()
    expected_depths = ["none", "none", "demographics", "demographics"]
    expected_blindings = ["blinded", "unblinded", "blinded", "unblinded"]
    for model_index, meta in enumerate(plan["models"]):
        legs = plan["legs"][model_index * 4:(model_index + 1) * 4]
        assert [leg["depth"] for leg in legs] == expected_depths, (
            f"{meta['model']}: legs must be the four standard legs in "
            "queue order"
        )
        assert [leg["blinding"] for leg in legs] == expected_blindings
        assert [leg["model"] for leg in legs] == [meta["model"]] * 4
        assert [leg["calls"] for leg in legs] == [440, 440, 8_800, 8_800], (
            f"{meta['model']}: per-leg call counts wrong: "
            f"{[leg['calls'] for leg in legs]}"
        )


def test_qwenext_plan_keeps_the_levels_and_seed_conventions():
    """Same design inputs as every profile: the 0-200% levels ride the
    plan untouched, seed and pool-seed default to 42, and pools are
    reused by default (no persona draws in the plan)."""
    plan = _qwenext_plan()
    assert plan["levels"] == LEVELS == [0.0, 20.0, 40.0, 60.0, 80.0,
                                        100.0, 120.0, 140.0, 160.0,
                                        180.0, 200.0], (
        f"the 0-200% levels must ride the plan untouched; got {plan['levels']}"
    )
    assert plan["seed"] == 42 and plan["pool_seed"] == 42
    assert plan["pool_draws"] == 0, "pools are reused by default (no draws)"


def test_qwenext_legs_are_durable_queue_legs(tmp_path):
    """The plan's legs are first-class queue legs: a slash-free safe_model,
    <run>/<model>/<depth>_<blinding> directories, records.jsonl (LEG_FILE)
    as the durable file, an untouched leg never counts as done, and a
    fresh --resume keeps every leg pending."""
    from launch_queue import (
        LEG_FILE,
        pending_queue_targets,
        queue_leg_dir,
        queue_leg_jsonl,
        queue_leg_done,
    )
    assert LEG_FILE == "records.jsonl"
    plan = _qwenext_plan()
    for leg in plan["legs"]:
        assert "/" not in leg["safe_model"], (
            f"safe_model must be filesystem-safe; got {leg['safe_model']!r}"
        )
        leg_dir = queue_leg_dir(tmp_path, leg)
        assert leg_dir == tmp_path / leg["safe_model"] / (
            f"{leg['depth']}_{leg['blinding']}"
        )
        assert queue_leg_jsonl(leg_dir) == leg_dir / LEG_FILE
        assert queue_leg_done(tmp_path, leg) is False, (
            "a leg with nothing on disk must never count as done"
        )
    assert pending_queue_targets(tmp_path, plan["legs"], resume=True) == plan["legs"], (
        "a fresh resume on an empty run dir must keep all 12 legs pending"
    )


# --- (5) Defaults: no override-map entries for the three models ----------

def test_qwenext_models_are_absent_from_the_top_k_override_map():
    """None of the three models has a top-k override: the profile config
    must not list them, and model_top_k answers the historical 20."""
    from launch_queue import MODEL_TOP_K_OVERRIDES, model_top_k
    from logprob_scoring import TOP_LOGPROBS

    assert TOP_LOGPROBS == 20
    module = _qwenext_module()
    for model in module.QWENEXT_MODEL_QUEUE:
        assert model not in MODEL_TOP_K_OVERRIDES, (
            f"{model} must have NO top-k override - it keeps the "
            f"historical coverage; map: {MODEL_TOP_K_OVERRIDES}"
        )
        assert model_top_k(model) == 20, (
            f"model_top_k({model!r}) must resolve to the historical 20; "
            f"got {model_top_k(model)}"
        )


def test_qwenext_models_are_absent_from_the_control_sequence_map():
    """None of the three models has a control-sequence override: the
    profile config must not list them, and model_control_sequences answers
    the default-off empty tuple (byte-identical scoring behavior)."""
    from launch_queue import MODEL_CONTROL_SEQUENCES, model_control_sequences

    module = _qwenext_module()
    for model in module.QWENEXT_MODEL_QUEUE:
        assert model not in MODEL_CONTROL_SEQUENCES, (
            f"{model} must have NO control-sequence override; "
            f"map keys: {sorted(MODEL_CONTROL_SEQUENCES)}"
        )
        assert model_control_sequences(model) == (), (
            f"model_control_sequences({model!r}) must resolve to the "
            f"identity empty tuple; got {model_control_sequences(model)}"
        )


# --- (6) Import: pure specification load, no socket -----------------------

def test_importing_the_qwenext_module_never_opens_a_socket(monkeypatch):
    """Importing the module is a pure specification load: with the socket
    constructor refused, a fresh import succeeds and nothing dials out."""
    # The launcher dependencies are import-safe by their own locked
    # contracts; load them BEFORE the guard so this test measures the new
    # module's own top-level code.
    import launch_queue  # noqa: F401
    from logprob_scoring import TOP_LOGPROBS  # noqa: F401

    monkeypatch.setattr(
        socket, "socket",
        _forbid_socket("importing launch_yesno_qwenext must not open a socket"),
    )
    monkeypatch.setattr(
        socket, "create_connection",
        _forbid_socket("importing launch_yesno_qwenext must not connect out"),
    )
    sys.modules.pop(MODULE_NAME, None)  # force a fresh import under the guard
    module = _qwenext_module()
    assert module.QWENEXT_PROFILE == "R1-YESNO-QWENEXT"


# --- (7) Dry run: the whole plan, printed offline -------------------------

def test_qwenext_dry_run_prints_the_whole_plan_offline(monkeypatch, capsys):
    """The plan printer prints the dry-run plan (profile header, all three
    models, per-model and total call counts) without contacting the model
    manager or any server - the socket constructor is refused for the whole
    call - and the purchase grammar never appears (this is a grammar-free
    yes/no logprob profile)."""
    monkeypatch.setattr(
        socket, "socket",
        _forbid_socket("the qwenext dry run must not contact any server"),
    )
    monkeypatch.setattr(
        socket, "create_connection",
        _forbid_socket("the qwenext dry run must not connect out"),
    )
    module = _qwenext_module()
    plan = _qwenext_plan()
    args = SimpleNamespace(
        manager_url="http://127.0.0.1:9", products="products.json", pools_from=""
    )
    module.print_qwenext_dry_run(args, [{"product": "Cola 12 oz"}], plan, Path("run"))
    out = capsys.readouterr().out
    assert "R1-YESNO-QWENEXT launch plan (dry run)" in out, (
        f"the dry run must announce its profile; got:\n{out}"
    )
    for model in QWENEXT_MODELS:
        assert model in out, f"the dry run must list {model}; got:\n{out}"
    assert "18,480" in out, f"per-model call count must be visible; got:\n{out}"
    assert "55,440" in out, f"the queue total must be visible; got:\n{out}"
    assert "root ::=" not in out, (
        "the purchase GBNF grammar must never appear in a QWENEXT plan - "
        "this profile is grammar-free like R1-YESNO"
    )
