# Locked tests for the R1-YESNO-NEWBATCH local companion batch run
# (TASK-1710, RED phase; tests ONLY - no implementation lives here;
# re-dispatch of TASK-1709 with the UPDATED run order).
#
# WHAT THIS FILE DOES: pins the contract for running FOUR brand-new GGUFs
# (Granite-4.1-8B, Gemma-4-12B-it-QAT, Granite-4.1-30B, Qwen3-32B) as ONE
# sequential queue through the EXACT R1-YESNO-QWENEXT geometry (the
# 3-model run's build_qwenext_plan(model_queue=...) pattern), as its own
# run dir so analysis merges it with the family. UPDATED vs TASK-1709:
# queue order is SMALLEST→LARGEST (user requirement) - the 8B proves the
# queue plumbing before the bigger models spend hours. All offline (no
# daemon, no GPU, no model loads, no network). Locked:
#   (1) PROFILE: QWENEXT_NEWBATCH_PROFILE = "R1-YESNO-NEWBATCH" - own
#       stamp, never colliding with the 3-model/GLM/QWEN36D/GEMMA31B
#       runs; accepted by launch_grid (PROFILES entry, 100 personas).
#   (2) QUEUE: QWENEXT_NEWBATCH_MODEL_QUEUE, exactly FOUR manager
#       registry ids, SMALLEST→LARGEST: ibm/granite-4.1-8b,
#       google/gemma-4-12b-it-qat, ibm/granite-4.1-30b, qwen/qwen3-32b.
#   (3) PLAN: the FULL QWENEXT geometry for four models - 16 legs,
#       880 + 17,600 = 18,480 cells/model, 73,920 total, shared
#       [40, 60) slice, pools reused, no grammar, one scoring pass.
#   (4) UNTOUCHED: the 3-model and GLM/QWEN36D/GEMMA31B plans are
#       byte-identical to today's; no new id leaks into them.
#   (5) LAUNCHER: --profile R1-YESNO-NEWBATCH mirrors R1-YESNO
#       (first_token yes/no, no grammar), own run-name stamp, offline
#       dry run, same DEFAULT_POOLS_FROM.
#   (6) RUNNER: plan-carried helpers drive the 4-model plan - no fork.
#   (7) REGISTRY: launcher ids == ~/fos-model-manager MODEL_REGISTRY ids
#       == pinned GGUF paths on disk. (Manager-side template branches -
#       qwen3-32b built-in, gemma-4-12b via a NEW branch ahead of the
#       generic gemma one, granites via a NEW granite branch - are
#       pinned in ~/fos-model-manager/test_registry_newbatch.py.)
#
# NOTES: the night sequence runs the Gemma-4-31B RESUME (R1-YESNO-
# GEMMA31B, 11,101/18,400 durable cells) BEFORE this batch - watchdog
# orchestration, not this profile. The locked tests in
# test_launch_yesno_qwenext.py, test_launch_qwenext_wiring.py,
# test_launch_qwenext_resume.py, test_launch_queue.py,
# test_launch_qwenext_glm.py, test_launch_qwen36d.py and
# test_launch_gemma31b.py must stay green. Nothing here touches a real
# server, the manager daemon, or any other run dir.
import importlib.util
import re
import socket
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


MODULE_NAME = "launch_yesno_qwenext"

# The batch's registry ids IN RUN ORDER - SMALLEST→LARGEST (user
# requirement) - and the exact GGUF file each one must load (all four
# freshly downloaded on 09-17, Q4 quants, verified on disk).
NEWBATCH_MODEL_IDS = (
    "ibm/granite-4.1-8b",
    "google/gemma-4-12b-it-qat",
    "ibm/granite-4.1-30b",
    "qwen/qwen3-32b",
)
NEWBATCH_GGUFS = {
    "ibm/granite-4.1-8b": (
        "/home/justin/.lmstudio/models/lmstudio-community/"
        "granite-4.1-8b-GGUF/granite-4.1-8b-Q4_K_M.gguf"
    ),
    "google/gemma-4-12b-it-qat": (
        "/home/justin/.lmstudio/models/lmstudio-community/"
        "gemma-4-12B-it-QAT-GGUF/gemma-4-12B-it-QAT-Q4_0.gguf"
    ),
    "ibm/granite-4.1-30b": (
        "/home/justin/.lmstudio/models/lmstudio-community/"
        "granite-4.1-30b-GGUF/granite-4.1-30b-Q4_K_M.gguf"
    ),
    "qwen/qwen3-32b": (
        "/home/justin/.lmstudio/models/lmstudio-community/"
        "Qwen3-32B-GGUF/Qwen3-32B-Q4_K_M.gguf"
    ),
}
# Each model's parameter count in billions, for the size-order lock.
NEWBATCH_MODEL_SIZES_B = {
    "ibm/granite-4.1-8b": 8,
    "google/gemma-4-12b-it-qat": 12,
    "ibm/granite-4.1-30b": 30,
    "qwen/qwen3-32b": 32,
}

# The full R1-YESNO design inputs (same as the 3-model QWENEXT run and
# every one-model companion): 40 products, 11 price levels 0-200%, one
# scoring pass per prompt.
PRODUCTS_COUNT = 40
LEVELS = [float(x) for x in range(0, 220, 20)]


def _qwenext_module():
    """The qwenext launcher module (the companion constants ride it)."""
    return importlib.import_module(MODULE_NAME)


def _newbatch_constants():
    """The NEWBATCH profile id and model queue, or a clear RED failure.

    Every batch test needs these two names; failing here names the
    missing feature instead of leaking an AttributeError.
    """
    module = _qwenext_module()
    profile = getattr(module, "QWENEXT_NEWBATCH_PROFILE", None)
    queue = getattr(module, "QWENEXT_NEWBATCH_MODEL_QUEUE", None)
    if profile is None or queue is None:
        pytest.fail(
            "launch_yesno_qwenext does not define the NEWBATCH constants "
            "yet (needs QWENEXT_NEWBATCH_PROFILE='R1-YESNO-NEWBATCH' and "
            f"QWENEXT_NEWBATCH_MODEL_QUEUE={NEWBATCH_MODEL_IDS!r}); got "
            f"profile={profile!r}, queue={queue!r}"
        )
    return profile, queue


def _build_newbatch_plan():
    """The NEWBATCH plan for the full R1-YESNO design inputs."""
    module = _qwenext_module()
    profile, queue = _newbatch_constants()
    try:
        return module.build_qwenext_plan(
            PRODUCTS_COUNT, len(LEVELS), levels=LEVELS,
            profile=profile, model_queue=queue,
        )
    except TypeError as exc:
        pytest.fail(
            f"build_qwenext_plan does not accept the NEWBATCH queue "
            f"(model_queue parameter regression?): {exc}"
        )


def _forbid_sockets(monkeypatch, reason: str) -> None:
    """Refuse every dial for the guarded block (offline proof)."""
    def _refuse(*_args, **_kwargs):
        raise AssertionError(reason)

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _launch_grid_args(profile):
    """launch_grid's parsed args for the NEWBATCH profile, or clear RED."""
    from launch_grid import _parse_args

    try:
        return _parse_args(["--profile", profile])
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {profile} (exit {exc.code}): the "
            "NEWBATCH profile is not registered in the launcher's --profile "
            "dispatch yet"
        )


# --- (1) Profile: the batch is its own run-level profile ------------------

def test_newbatch_profile_constant_is_defined_and_distinct():
    """The batch runs under its OWN profile id R1-YESNO-NEWBATCH: the
    same yes/no study family, but never the 3-model run's profile or any
    companion's, so analysis can tell all the run dirs apart."""
    module = _qwenext_module()
    profile, _queue = _newbatch_constants()
    assert profile == "R1-YESNO-NEWBATCH", (
        f"the NEWBATCH profile must be 'R1-YESNO-NEWBATCH'; got {profile!r}"
    )
    assert profile != module.QWENEXT_PROFILE
    assert profile != module.QWENEXT_GLM_PROFILE, "must not reuse the GLM stamp"
    assert profile != module.QWENEXT_QWEN36D_PROFILE, "must not reuse the QWEN36D stamp"
    assert profile != module.QWENEXT_GEMMA31B_PROFILE, "must not reuse the GEMMA31B stamp"
    assert profile.startswith("R1-YESNO-"), (
        "the NEWBATCH profile must extend the R1-YESNO naming so the "
        "runs read as one study family"
    )


def test_newbatch_profile_is_registered_in_the_launcher_profiles():
    """launch_grid's --profile choices come from launch_support.PROFILES,
    so NEWBATCH must be registered there with the study-standard
    100-persona pool - or the launcher refuses the profile up front."""
    profile, _queue = _newbatch_constants()
    from launch_support import PROFILES

    assert profile in PROFILES, (
        f"{profile!r} is missing from launch_support.PROFILES "
        f"({sorted(PROFILES)}) - launch_grid's --profile dispatch can "
        "never select it"
    )
    assert PROFILES[profile] == 100, f"the batch shares the 100-persona pool; got {PROFILES[profile]!r}"


# --- (2) Queue: exactly the four new models, SMALLEST→LARGEST -------------

def test_newbatch_queue_is_exactly_the_four_new_models_smallest_to_largest():
    """The queue is exactly the four new models in SMALLEST→LARGEST run
    order (user requirement): granite-4.1-8b, gemma-4-12b-it-qat,
    granite-4.1-30b, qwen3-32b - each the manager registry id, character
    for character (locked against the registry below). The smallest runs
    first so the queue plumbing is proven cheaply."""
    _profile, queue = _newbatch_constants()
    assert queue == NEWBATCH_MODEL_IDS, (
        f"QWENEXT_NEWBATCH_MODEL_QUEUE must be exactly "
        f"{NEWBATCH_MODEL_IDS!r} (SMALLEST→LARGEST run order matters: "
        f"one sequential queue, loaded back to back); got {queue!r}"
    )
    assert len(queue) == 4 and len(set(queue)) == 4, "four distinct ids"
    sizes = [NEWBATCH_MODEL_SIZES_B[model_id] for model_id in queue]
    assert sizes == sorted(sizes), (
        f"the queue must run SMALLEST→LARGEST; got sizes {sizes}B for "
        f"{queue!r}"
    )


# --- (3) Plan: the full QWENEXT geometry for exactly four models ----------

def test_newbatch_plan_carries_the_full_qwenext_geometry_for_four_models():
    """The plan is the R1-YESNO geometry exactly, for four models: 16
    legs, 880 + 17,600 = 18,480 calls per model and 73,920 total, the
    SHARED [40, 60) persona slice for EVERY model, pools reused, one
    scoring pass per prompt, the NEWBATCH profile stamp."""
    from launch_queue import LOGP_NONE_DRAWS, PERSONAS_PER_MODEL

    assert LOGP_NONE_DRAWS == 1
    _profile, queue = _newbatch_constants()
    plan = _build_newbatch_plan()
    assert plan["profile"] == "R1-YESNO-NEWBATCH", (
        f"the NEWBATCH plan must carry its own profile stamp, not the "
        f"3-model run's {plan['profile']!r}"
    )
    assert len(plan["models"]) == 4, (
        f"exactly four batch models; got {len(plan['models'])}"
    )
    for index, meta in enumerate(plan["models"]):
        assert meta["model"] == queue[index], (
            f"model slot {index} must be {queue[index]!r} (run order); "
            f"got {meta['model']!r}"
        )
        assert meta["model_index"] == index
        assert "/" not in meta["safe_model"], "safe_model must be filesystem-safe"
        assert meta["persona_slice"] == [40, 60], (
            f"{meta['model']} must answer the SHARED [40, 60) slice; "
            f"got {meta['persona_slice']}"
        )
        assert meta["none_calls"] == 880, f"2 x 40 x 11 x 1 = 880 bare cells; got {meta['none_calls']}"
        assert meta["demographics_calls"] == 17_600, (
            f"2 x 40 x 20 x 11 = 17,600 demographics cells; "
            f"got {meta['demographics_calls']}"
        )
        assert meta["total_calls"] == 18_480
    assert len(plan["legs"]) == 16, (
        f"4 models x 4 legs; got {len(plan['legs'])}"
    )
    for model_pos in range(4):
        legs = plan["legs"][model_pos * 4:(model_pos + 1) * 4]
        assert [
            (leg["depth"], leg["blinding"], leg["calls"]) for leg in legs
        ] == [
            ("none", "blinded", 440), ("none", "unblinded", 440),
            ("demographics", "blinded", 8_800), ("demographics", "unblinded", 8_800),
        ]
        assert all(
            leg["model"] == queue[model_pos] and leg["model_index"] == model_pos
            for leg in legs
        ), f"legs {model_pos * 4}..{model_pos * 4 + 3} must belong to {queue[model_pos]!r}"
    assert plan["sweep_calls"] == 73_920, f"4 x 18,480 = 73,920; got {plan['sweep_calls']}"
    assert plan["draws"] == 1, "one scoring pass per prompt, like R1-YESNO"
    assert plan["k"] == 100 and plan["per_model_personas"] == PERSONAS_PER_MODEL
    assert plan["pool_draws"] == 0, "pools are reused (no persona draws)"
    assert plan["seed"] == 42 and plan["pool_seed"] == 42
    assert plan["levels"] == LEVELS, "the 0-200% levels ride the plan untouched"


def test_default_qwenext_and_all_companion_plans_are_unchanged_by_the_new_queue():
    """Adding the batch must not disturb the four existing specs: the
    default build_qwenext_plan call still yields the 3-model QWENEXT
    plan, the GLM/QWEN36D/GEMMA31B companions still build exactly as
    today, and no new id leaks into any of them."""
    module = _qwenext_module()
    default_plan = module.build_qwenext_plan(2, 2, levels=[0.0, 100.0])
    assert default_plan["profile"] == "R1-YESNO-QWENEXT"
    assert len(default_plan["models"]) == 3
    assert len(default_plan["legs"]) == 12
    # Probe scale (2 products x 2 levels): per model 2x2x2x1 = 8 bare +
    # 2x2x20x2 = 160 demographics = 168; x3 models = 504.
    assert default_plan["sweep_calls"] == 3 * (8 + 160) == 504
    explicit_plan = module.build_qwenext_plan(
        2, 2, levels=[0.0, 100.0],
        model_queue=module.QWENEXT_MODEL_QUEUE,
    )
    assert default_plan == explicit_plan, (
        "building without the parameter must equal the explicit 3-model "
        "queue (the executed run's spec cannot shift)"
    )
    glm_plan = module.build_qwenext_plan(
        2, 2, levels=[0.0, 100.0],
        profile=module.QWENEXT_GLM_PROFILE,
        model_queue=module.QWENEXT_GLM_MODEL_QUEUE,
    )
    assert glm_plan["profile"] == "R1-YESNO-QWENEXT-GLM"
    assert len(glm_plan["models"]) == 1
    assert len(glm_plan["legs"]) == 4
    assert glm_plan["models"][0]["model"] == "glm/glm-4.7-flash"
    assert glm_plan["sweep_calls"] == 168
    qwen36d_plan = module.build_qwenext_plan(
        2, 2, levels=[0.0, 100.0],
        profile=module.QWENEXT_QWEN36D_PROFILE,
        model_queue=module.QWENEXT_QWEN36D_MODEL_QUEUE,
    )
    assert qwen36d_plan["profile"] == "R1-YESNO-QWEN36D"
    assert len(qwen36d_plan["models"]) == 1
    assert len(qwen36d_plan["legs"]) == 4
    assert qwen36d_plan["models"][0]["model"] == "qwen/qwen3.6-27b-dense"
    assert qwen36d_plan["sweep_calls"] == 168
    gemma31b_plan = module.build_qwenext_plan(
        2, 2, levels=[0.0, 100.0],
        profile=module.QWENEXT_GEMMA31B_PROFILE,
        model_queue=module.QWENEXT_GEMMA31B_MODEL_QUEUE,
    )
    assert gemma31b_plan["profile"] == "R1-YESNO-GEMMA31B"
    assert len(gemma31b_plan["models"]) == 1
    assert len(gemma31b_plan["legs"]) == 4
    assert gemma31b_plan["models"][0]["model"] == "google/gemma-4-31b-it-qat"
    assert gemma31b_plan["sweep_calls"] == 168
    for new_id in NEWBATCH_MODEL_IDS:
        for label, other_plan in (
            ("3-model", default_plan), ("GLM", glm_plan),
            ("QWEN36D", qwen36d_plan), ("GEMMA31B", gemma31b_plan),
        ):
            assert new_id not in str(other_plan), (
                f"the new model {new_id} must not leak into the {label} plan"
            )


# --- (5) Launcher: reachable through launch_grid's --profile dispatch -----

def test_newbatch_profile_is_reachable_from_the_launcher_dry_run(
    monkeypatch, capsys
):
    """launch_grid --profile R1-YESNO-NEWBATCH --dry-run is accepted
    through the SAME --profile dispatch that starts R1-5MODEL / R1LP /
    R1-YESNO / the QWENEXT queues, prints the four-model batch plan, and
    never dials (the socket constructor is refused for the whole
    call)."""
    _forbid_sockets(monkeypatch, "the NEWBATCH dry run must not contact anything")
    profile, queue = _newbatch_constants()
    from launch_grid import main

    try:
        code = main(["--profile", profile, "--dry-run"])
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {profile} (exit {exc.code}): the "
            "NEWBATCH profile is not registered in the launcher's --profile "
            "dispatch yet"
        )
    assert code == 0
    out = capsys.readouterr().out
    assert f"{profile} launch plan (dry run)" in out, f"dry run must announce the profile; got:\n{out}"
    for model_id in queue:
        assert model_id in out, f"the dry run must list {model_id}; got:\n{out}"
    assert "pool personas 40-59" in out, f"must show the shared [40, 60) slice; got:\n{out}"
    assert "73,920" in out, f"the queue total must be visible; got:\n{out}"
    assert "root ::=" not in out, (
        "the purchase grammar must never appear - this profile is "
        "grammar-free like R1-YESNO"
    )


def test_newbatch_settings_score_first_token_yes_no_without_grammar():
    """The NEWBATCH settings mirror R1-YESNO/QWENEXT and the companions
    exactly: first_token scoring, the yes/no response words, and no
    grammar."""
    profile, _queue = _newbatch_constants()
    from launch_grid import _settings_from

    settings = _settings_from(_launch_grid_args(profile), "newbatch-probe")
    assert settings.logprob_mode == "first_token", (
        f"the NEWBATCH batch must score first_token like R1-YESNO; got "
        f"{settings.logprob_mode!r}"
    )
    assert settings.response_format == "yes/no", (
        f"the NEWBATCH batch must ask the yes/no response words; got "
        f"{settings.response_format!r}"
    )
    assert settings.grammar is None, "the NEWBATCH batch is grammar-free like R1-YESNO"


def test_newbatch_default_run_name_is_its_own_distinct_stamp():
    """The NEWBATCH default run name is its own stamp
    R1-YESNO-NEWBATCH-<YYYYMMDDTHHMMSS> (the queue-profile stamp branch,
    no model stem) - never colliding with the 3-model run's
    R1-YESNO-QWENEXT-<stamp> or any companion's dirs, so analysis can
    merge run dirs unambiguously."""
    profile, _queue = _newbatch_constants()
    from launch_grid import _build_run_name

    name = _build_run_name(_launch_grid_args(profile))
    assert re.fullmatch(r"R1-YESNO-NEWBATCH-\d{8}T\d{6}", name), (
        f"the NEWBATCH default run name must be its own profile stamp "
        f"(R1-YESNO-NEWBATCH-<YYYYMMDDTHHMMSS>, the queue-profile branch, "
        f"no model stem); got {name!r}"
    )


def test_newbatch_reuses_the_same_default_pools():
    """The NEWBATCH reuses the same archived pools as the 3-model run and
    the companions: the launcher's --pools-from default
    (DEFAULT_POOLS_FROM) applies to the NEWBATCH profile invocation
    unchanged."""
    profile, _queue = _newbatch_constants()
    from launch_5model import DEFAULT_POOLS_FROM

    assert DEFAULT_POOLS_FROM == (
        "results/unblinding/R1-nemotron-cascade-2-30b-a3b-20260909T004614/pools"
    )
    args = _launch_grid_args(profile)
    assert args.pools_from == DEFAULT_POOLS_FROM, (
        f"the NEWBATCH batch must reuse the study's shared pools by "
        f"default; got pools_from={args.pools_from!r}"
    )


# --- (6) Runner: the plan-carried helpers drive a 4-model plan ------------

def test_queue_runner_helpers_drive_a_four_model_newbatch_plan_unchanged(tmp_path):
    """No runner fork: the existing plan-carried helpers read the NEWBATCH
    plan (queue of four, shared slice for every index, the usual leg
    durability on disk for all 16 legs)."""
    from launch_queue import (
        LEG_FILE, pending_queue_targets, plan_model_queue,
        plan_persona_slice, queue_leg_dir, queue_leg_done, queue_leg_jsonl,
    )
    assert LEG_FILE == "records.jsonl"
    _profile, queue = _newbatch_constants()
    plan = _build_newbatch_plan()
    assert plan_model_queue(plan) == queue, (
        f"plan_model_queue must read the 4-model queue from the plan; got "
        f"{plan_model_queue(plan)!r}"
    )
    for index in range(len(queue)):
        assert plan_persona_slice(plan, index) == (40, 60), (
            f"plan_persona_slice must read the shared [40, 60) slice for "
            f"queue index {index}; got {plan_persona_slice(plan, index)!r}"
        )
    for leg in plan["legs"]:
        leg_dir = queue_leg_dir(tmp_path, leg)
        assert leg_dir == tmp_path / leg["safe_model"] / f"{leg['depth']}_{leg['blinding']}"
        assert queue_leg_jsonl(leg_dir) == leg_dir / LEG_FILE
        assert queue_leg_done(tmp_path, leg) is False, (
            "a leg with nothing on disk must never count as done"
        )
    assert pending_queue_targets(tmp_path, plan["legs"], resume=True) == plan["legs"], (
        "a fresh resume on an empty run dir must keep all 16 legs pending"
    )


# --- (7) Registry: the launcher ids are the manager's registered ids ------

def test_newbatch_registry_ids_match_the_model_manager_registry():
    """Every launcher id is registered in ~/fos-model-manager's
    MODEL_REGISTRY, each registered GGUF path is exactly the pinned file,
    and each file exists on disk. (The registry lines do not exist yet -
    this test drives them.)"""
    _profile, queue = _newbatch_constants()
    manager_path = Path.home() / "fos-model-manager" / "model_manager.py"
    if not manager_path.is_file():
        pytest.skip(
            "the model manager (~/fos-model-manager/model_manager.py) is not "
            "installed on this machine; the manager-side test file pins the "
            "registry there"
        )
    spec = importlib.util.spec_from_file_location(
        "model_manager_newbatch_crosscheck", manager_path
    )
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    registry = manager.MODEL_REGISTRY
    for model_id in queue:
        expected = NEWBATCH_GGUFS[model_id]
        assert model_id in registry, (
            f"{model_id!r} is missing from MODEL_REGISTRY in "
            f"{manager_path} - the launcher id and the manager registry id "
            f"must match character for character; registered ids: "
            f"{sorted(registry)}"
        )
        assert registry[model_id] == expected, (
            f"MODEL_REGISTRY[{model_id!r}] must point at the pinned file "
            f"{expected!r}; got {registry[model_id]!r}"
        )
        assert Path(expected).is_file(), (
            f"the registered GGUF does not exist on disk: {expected}"
        )
