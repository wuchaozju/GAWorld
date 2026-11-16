# Locked tests for the R1-YESNO-QWEN36D **local Qwen3.6-27B-dense
# companion run** (TASK-1689, RED phase; tests ONLY - no implementation
# lives here).
#
# WHY THESE TESTS EXIST: the user downloaded the brand-new dense
# Qwen3.6-27B GGUF and wants it run through the EXACT R1-YESNO-QWENEXT
# geometry - the same pipeline as the 3-model QWENEXT run and the GLM
# companion - so its demand curves compare 1:1 with local qwen3.8-27b and
# the rest of the family. It launches as its own run (own profile stamp)
# through the LOCAL model manager, mirroring the GLM companion pattern:
# a profile constant + a one-model queue + build_qwenext_plan
# (model_queue=...) parameterization. These tests pin that contract, all
# offline (no manager daemon, no GPU, no model loads, no network).
# Locked here:
#
#   (1) PROFILE: launch_yesno_qwenext names the new companion profile
#       QWENEXT_QWEN36D_PROFILE = "R1-YESNO-QWEN36D" - clearly the same
#       study but never colliding with the 3-model or GLM run stamps -
#       and launch_grid's --profile dispatch accepts it (PROFILES entry).
#   (2) QUEUE: exactly ONE model, the manager registry id
#       "qwen/qwen3.6-27b-dense" (character for character).
#   (3) PLAN: build_qwenext_plan(model_queue=...) reproduces the FULL
#       QWENEXT geometry for exactly one model: 4 legs (none/demographics
#       x blinded/unblinded), 880 + 17,600 = 18,480 cells, the SHARED
#       [40, 60) persona slice, pools reused (pool_draws 0), no grammar,
#       one scoring pass per prompt, and the plan stamped with the
#       companion profile id.
#   (4) UNTOUCHED: the default 3-model R1-YESNO-QWENEXT plan and the
#       R1-YESNO-QWENEXT-GLM companion plan are byte-identical to today's.
#   (5) LAUNCHER: --profile R1-YESNO-QWEN36D goes through launch_grid's
#       established --profile dispatch; its settings mirror R1-YESNO
#       (first_token, yes/no words, no grammar); its default run name is
#       its own stamp R1-YESNO-QWEN36D-<YYYYMMDDTHHMMSS>; its dry run
#       prints the whole plan offline; it reuses the same
#       DEFAULT_POOLS_FROM.
#   (6) RUNNER: the plan-carried helpers (plan_model_queue /
#       plan_persona_slice / leg durability) drive the 1-model plan
#       unchanged - no runner fork.
#   (7) REGISTRY: the launcher's dense-model id equals the id registered
#       in ~/fos-model-manager MODEL_REGISTRY, whose GGUF path exists on
#       disk and is exactly the Q4_K_M file. (The manager-side branch
#       behavior - the id starts llama-server on its BUILT-IN template
#       because the id contains "qwen" - is pinned in
#       ~/fos-model-manager/test_registry_qwen36_27b_dense.py.)
#
# The locked tests in test_launch_yesno_qwenext.py, test_launch_qwenext_
# wiring.py, test_launch_qwenext_resume.py, test_launch_queue.py and
# test_launch_qwenext_glm.py must stay green. No test here touches a real
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

# The dense companion's registry id and the exact GGUF file on disk
# (freshly downloaded, 16.5 GB Q4_K_M).
QWEN36D_MODEL_ID = "qwen/qwen3.6-27b-dense"
QWEN36D_GGUF = (
    "/home/justin/.lmstudio/models/lmstudio-community/"
    "Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf"
)

# The full R1-YESNO design inputs (same as the 3-model QWENEXT run and
# the GLM companion): 40 products, 11 price levels 0-200%, one scoring
# pass per prompt.
PRODUCTS_COUNT = 40
LEVELS = [float(x) for x in range(0, 220, 20)]


def _qwenext_module():
    """The qwenext launcher module (the companion constants ride it)."""
    return importlib.import_module(MODULE_NAME)


def _qwen36d_constants():
    """The dense companion's profile id and model queue, or a clear RED
    failure.

    Every companion test needs these two names; failing here names the
    missing feature instead of leaking an AttributeError.
    """
    module = _qwenext_module()
    profile = getattr(module, "QWENEXT_QWEN36D_PROFILE", None)
    queue = getattr(module, "QWENEXT_QWEN36D_MODEL_QUEUE", None)
    if profile is None or queue is None:
        pytest.fail(
            "launch_yesno_qwenext does not define the Qwen3.6-27B-dense "
            "companion constants yet (needs "
            "QWENEXT_QWEN36D_PROFILE='R1-YESNO-QWEN36D' and "
            f"QWENEXT_QWEN36D_MODEL_QUEUE=({QWEN36D_MODEL_ID!r},)); got "
            f"profile={profile!r}, queue={queue!r}"
        )
    return profile, queue


def _build_qwen36d_plan():
    """The dense companion plan for the full R1-YESNO design inputs."""
    module = _qwenext_module()
    profile, queue = _qwen36d_constants()
    try:
        return module.build_qwenext_plan(
            PRODUCTS_COUNT, len(LEVELS), levels=LEVELS,
            profile=profile, model_queue=queue,
        )
    except TypeError as exc:
        pytest.fail(
            "build_qwenext_plan does not accept the new companion queue "
            f"(model_queue parameter regression?): {exc}"
        )


def _forbid_sockets(monkeypatch, reason: str) -> None:
    """Refuse every dial for the guarded block (offline proof)."""
    def _refuse(*_args, **_kwargs):
        raise AssertionError(reason)

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- (1) Profile: the companion is its own run-level profile --------------

def test_qwen36d_companion_profile_constant_is_defined_and_distinct():
    """The dense companion runs under its OWN profile id
    R1-YESNO-QWEN36D: clearly the same yes/no study (it extends the
    R1-YESNO naming) but never the 3-model run's profile or the GLM
    companion's, so analysis can tell all three run dirs apart."""
    module = _qwenext_module()
    profile, _queue = _qwen36d_constants()
    assert profile == "R1-YESNO-QWEN36D", (
        f"the dense companion profile must be 'R1-YESNO-QWEN36D' (the "
        f"same study family as {module.QWENEXT_PROFILE!r}, distinguishable "
        f"for the analysis merge); got {profile!r}"
    )
    assert profile != module.QWENEXT_PROFILE
    assert profile != module.QWENEXT_GLM_PROFILE, (
        "the dense companion must not reuse the GLM companion's profile "
        f"({module.QWENEXT_GLM_PROFILE!r}) - the two runs merge as "
        "separate run dirs"
    )
    assert profile.startswith("R1-YESNO-"), (
        "the companion profile must extend the R1-YESNO naming so the "
        "runs read as one study family"
    )


def test_qwen36d_companion_profile_is_registered_in_the_launcher_profiles():
    """launch_grid's --profile choices come from launch_support.PROFILES,
    so the dense companion's profile must be registered there with the
    study-standard 100-persona pool - otherwise the launcher refuses the
    profile before any plan is built."""
    profile, _queue = _qwen36d_constants()
    from launch_support import PROFILES

    assert profile in PROFILES, (
        f"{profile!r} is missing from launch_support.PROFILES "
        f"({sorted(PROFILES)}) - launch_grid's --profile dispatch can "
        "never select it"
    )
    assert PROFILES[profile] == 100, (
        f"the dense companion shares the study's 100-persona pool; got "
        f"PROFILES[{profile!r}] = {PROFILES[profile]!r}"
    )


# --- (2) Queue: exactly the one dense model --------------------------------

def test_qwen36d_companion_queue_is_exactly_the_one_dense_model():
    """The dense companion queue is exactly ("qwen/qwen3.6-27b-dense",) -
    the manager registry id, character for character (locked against the
    registry in test_qwen36d_registry_id_matches_the_model_manager_registry
    below)."""
    _profile, queue = _qwen36d_constants()
    assert queue == (QWEN36D_MODEL_ID,), (
        f"QWENEXT_QWEN36D_MODEL_QUEUE must be exactly "
        f"({QWEN36D_MODEL_ID!r},); got {queue!r}"
    )


# --- (3) Plan: the full QWENEXT geometry for exactly one model ------------

def test_qwen36d_companion_plan_carries_the_full_qwenext_geometry_for_one_model():
    """The dense plan is the R1-YESNO geometry exactly, for one model: 4
    legs (none/demographics x blinded/unblinded), 880 bare + 17,600
    demographics = 18,480 calls, the SHARED [40, 60) persona slice, pools
    reused, one scoring pass per prompt, and the plan stamped with the
    companion profile id (not the 3-model run's, not the GLM's)."""
    from launch_queue import LOGP_NONE_DRAWS, PERSONAS_PER_MODEL

    assert LOGP_NONE_DRAWS == 1
    plan = _build_qwen36d_plan()
    assert plan["profile"] == "R1-YESNO-QWEN36D", (
        f"the dense companion plan must carry its own profile stamp, not "
        f"the 3-model run's {plan['profile']!r}"
    )
    assert len(plan["models"]) == 1, (
        f"exactly one companion model; got {len(plan['models'])}"
    )
    meta = plan["models"][0]
    assert meta["model"] == QWEN36D_MODEL_ID
    assert meta["model_index"] == 0
    assert "/" not in meta["safe_model"], "safe_model must be filesystem-safe"
    assert meta["persona_slice"] == [40, 60], (
        f"the dense model must answer the SAME shared [40, 60) slice as "
        f"qwen3.8-27b and the QWENEXT family; got {meta['persona_slice']}"
    )
    assert meta["none_calls"] == 880, (
        f"2 x 40 x 11 x 1 = 880 bare cells; got {meta['none_calls']}"
    )
    assert meta["demographics_calls"] == 17_600, (
        f"2 x 40 x 20 x 11 = 17,600 demographics cells; "
        f"got {meta['demographics_calls']}"
    )
    assert meta["total_calls"] == 18_480
    assert len(plan["legs"]) == 4, f"1 model x 4 legs; got {len(plan['legs'])}"
    assert [leg["depth"] for leg in plan["legs"]] == [
        "none", "none", "demographics", "demographics"
    ]
    assert [leg["blinding"] for leg in plan["legs"]] == [
        "blinded", "unblinded", "blinded", "unblinded"
    ]
    assert [leg["calls"] for leg in plan["legs"]] == [440, 440, 8_800, 8_800]
    assert all(leg["model"] == QWEN36D_MODEL_ID for leg in plan["legs"])
    assert plan["sweep_calls"] == 18_480, (
        f"one model x 18,480 cells; got {plan['sweep_calls']}"
    )
    assert plan["draws"] == 1, "one scoring pass per prompt, like R1-YESNO"
    assert plan["k"] == 100 and plan["per_model_personas"] == PERSONAS_PER_MODEL
    assert plan["pool_draws"] == 0, "pools are reused (no persona draws)"
    assert plan["seed"] == 42 and plan["pool_seed"] == 42
    assert plan["levels"] == LEVELS, "the 0-200% levels ride the plan untouched"


def test_default_qwenext_and_glm_companion_plans_are_unchanged_by_the_new_queue():
    """Adding the dense companion must not disturb the two existing specs:
    calling build_qwenext_plan WITHOUT the model_queue parameter still
    yields the 3-model QWENEXT plan (identical to passing the explicit
    3-model queue), and the GLM companion plan still builds exactly as
    today - 1 model, 4 legs, 18,480 calls, GLM profile stamp."""
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
        "building with the model_queue parameter defaulted to the 3-model "
        "queue must produce the identical plan (the executed run's spec "
        "cannot shift)"
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
    # Same probe scale for the GLM companion: 1 x 168 calls.
    assert glm_plan["sweep_calls"] == 168
    assert "qwen/qwen3.6-27b-dense" not in str(default_plan), (
        "the dense model must not leak into the default 3-model plan"
    )
    assert "qwen/qwen3.6-27b-dense" not in str(glm_plan), (
        "the dense model must not leak into the GLM companion plan"
    )


# --- (5) Launcher: reachable through launch_grid's --profile dispatch -----

def test_qwen36d_profile_is_reachable_from_the_launcher_dry_run(
    monkeypatch, capsys
):
    """launch_grid --profile R1-YESNO-QWEN36D --dry-run is accepted through
    the SAME --profile dispatch that starts R1-5MODEL / R1LP / R1-YESNO /
    R1-YESNO-QWENEXT / R1-YESNO-QWENEXT-GLM, prints the one-model dense
    plan, and never dials (the socket constructor is refused for the whole
    call)."""
    _forbid_sockets(monkeypatch, "the dense dry run must not contact anything")
    profile, _queue = _qwen36d_constants()
    from launch_grid import main

    try:
        code = main(["--profile", profile, "--dry-run"])
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {profile} (exit {exc.code}): the "
            "dense companion profile is not registered in the launcher's "
            "--profile dispatch yet"
        )
    assert code == 0
    out = capsys.readouterr().out
    assert f"{profile} launch plan (dry run)" in out, (
        f"the dry run must announce the companion profile; got:\n{out}"
    )
    assert QWEN36D_MODEL_ID in out, (
        f"the dry run must list {QWEN36D_MODEL_ID}; got:\n{out}"
    )
    assert "pool personas 40-59" in out, (
        f"the dry run must show the shared [40, 60) slice; got:\n{out}"
    )
    assert "18,480" in out, f"the queue total must be visible; got:\n{out}"
    assert "root ::=" not in out, (
        "the purchase grammar must never appear - this profile is "
        "grammar-free like R1-YESNO"
    )


def test_qwen36d_settings_score_first_token_yes_no_without_grammar():
    """The dense companion's settings mirror R1-YESNO/QWENEXT/GLM exactly:
    first_token scoring, the yes/no response words, and no grammar."""
    profile, _queue = _qwen36d_constants()
    from launch_grid import _parse_args, _settings_from

    try:
        args = _parse_args(["--profile", profile])
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {profile} (exit {exc.code}): the "
            "dense companion profile is not registered yet"
        )
    settings = _settings_from(args, "qwen36d-companion-probe")
    assert settings.logprob_mode == "first_token", (
        f"the dense companion must score first_token like R1-YESNO; got "
        f"{settings.logprob_mode!r}"
    )
    assert settings.response_format == "yes/no", (
        f"the dense companion must ask the yes/no response words; got "
        f"{settings.response_format!r}"
    )
    assert settings.grammar is None, (
        "the dense companion is grammar-free like R1-YESNO"
    )


def test_qwen36d_default_run_name_is_its_own_distinct_stamp():
    """The dense companion's default run name is its own stamp
    R1-YESNO-QWEN36D-<YYYYMMDDTHHMMSS> (the queue-profile stamp branch, no
    model stem) - never colliding with the 3-model run's
    R1-YESNO-QWENEXT-<stamp> or the GLM's R1-YESNO-QWENEXT-GLM-<stamp>
    dirs, so analysis can merge run dirs unambiguously."""
    profile, _queue = _qwen36d_constants()
    from launch_grid import _build_run_name, _parse_args

    try:
        args = _parse_args(["--profile", profile])
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {profile} (exit {exc.code}): the "
            "dense companion profile is not registered yet"
        )
    name = _build_run_name(args)
    assert re.fullmatch(r"R1-YESNO-QWEN36D-\d{8}T\d{6}", name), (
        f"the dense companion's default run name must be its own profile "
        f"stamp (R1-YESNO-QWEN36D-<YYYYMMDDTHHMMSS>, the queue-profile "
        f"branch, no model stem); got {name!r}"
    )


def test_qwen36d_reuses_the_same_default_pools():
    """The dense companion reuses the same archived pools as the 3-model
    run and the GLM companion: the launcher's --pools-from default
    (DEFAULT_POOLS_FROM) applies to the dense profile invocation
    unchanged."""
    profile, _queue = _qwen36d_constants()
    from launch_5model import DEFAULT_POOLS_FROM
    from launch_grid import _parse_args

    assert DEFAULT_POOLS_FROM == (
        "results/unblinding/R1-nemotron-cascade-2-30b-a3b-20260909T004614/pools"
    )
    try:
        args = _parse_args(["--profile", profile])
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {profile} (exit {exc.code}): the "
            "dense companion profile is not registered yet"
        )
    assert args.pools_from == DEFAULT_POOLS_FROM, (
        f"the dense companion must reuse the study's shared pools by "
        f"default; got pools_from={args.pools_from!r}"
    )


# --- (6) Runner: the plan-carried helpers drive a 1-model plan ------------

def test_queue_runner_helpers_drive_a_one_model_qwen36d_plan_unchanged(tmp_path):
    """No runner fork: the existing plan-carried helpers read the dense
    plan (queue of one, shared slice, the usual leg durability on disk)."""
    from launch_queue import (
        LEG_FILE,
        pending_queue_targets,
        plan_model_queue,
        plan_persona_slice,
        queue_leg_dir,
        queue_leg_done,
        queue_leg_jsonl,
    )
    assert LEG_FILE == "records.jsonl"
    plan = _build_qwen36d_plan()
    assert plan_model_queue(plan) == (QWEN36D_MODEL_ID,), (
        f"plan_model_queue must read the 1-model queue from the plan; got "
        f"{plan_model_queue(plan)!r}"
    )
    assert plan_persona_slice(plan, 0) == (40, 60), (
        f"plan_persona_slice must read the shared [40, 60) slice from the "
        f"plan; got {plan_persona_slice(plan, 0)!r}"
    )
    for leg in plan["legs"]:
        leg_dir = queue_leg_dir(tmp_path, leg)
        assert leg_dir == tmp_path / leg["safe_model"] / (
            f"{leg['depth']}_{leg['blinding']}"
        )
        assert queue_leg_jsonl(leg_dir) == leg_dir / LEG_FILE
        assert queue_leg_done(tmp_path, leg) is False, (
            "a leg with nothing on disk must never count as done"
        )
    assert pending_queue_targets(tmp_path, plan["legs"], resume=True) == plan["legs"], (
        "a fresh resume on an empty run dir must keep all 4 legs pending"
    )


# --- (7) Registry: the launcher id is the manager's registered id ---------

def test_qwen36d_registry_id_matches_the_model_manager_registry():
    """The launcher's dense-model id is registered in
    ~/fos-model-manager's MODEL_REGISTRY, the registered GGUF path is
    exactly the Q4_K_M file, and that file exists on disk. (The registry
    line does not exist yet - this test drives it.)"""
    _profile, queue = _qwen36d_constants()
    dense_id = queue[0]
    manager_path = Path.home() / "fos-model-manager" / "model_manager.py"
    if not manager_path.is_file():
        pytest.skip(
            "the model manager (~/fos-model-manager/model_manager.py) is not "
            "installed on this machine; the manager-side test file pins the "
            "registry there"
        )
    spec = importlib.util.spec_from_file_location(
        "model_manager_qwen36d_crosscheck", manager_path
    )
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    registry = manager.MODEL_REGISTRY
    assert dense_id in registry, (
        f"{dense_id!r} is missing from MODEL_REGISTRY in "
        f"{manager_path} - the launcher id and the manager registry id must "
        f"match character for character; registered ids: {sorted(registry)}"
    )
    assert registry[dense_id] == QWEN36D_GGUF, (
        f"MODEL_REGISTRY[{dense_id!r}] must point at the Q4_K_M file "
        f"{QWEN36D_GGUF!r}; got {registry[dense_id]!r}"
    )
    assert Path(QWEN36D_GGUF).is_file(), (
        f"the registered GGUF does not exist on disk: {QWEN36D_GGUF}"
    )
