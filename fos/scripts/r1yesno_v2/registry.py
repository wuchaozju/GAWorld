# This file is the address book of the study: for each of the 16 language
# models it records where the answer files live on disk, how the purchase
# probability was measured, and the model facts (family, architecture,
# parameter count) used to draw the figures. Its functions:
#   model_dir — full path to one model's answer folder inside a results root;
#   verify_registry_paths — check that every registered answer file exists,
#     and list loudly anything on disk that the registry does not know;
#   canonical_metadata_rows — the model facts as table rows, ready for the
#     model_metadata.csv output.

from __future__ import annotations

from pathlib import Path

# Probability measures (see research R1YESNO-V2 METHODS.md):
#   logprob_p_yes_binary — yes/no first-token logprob measure, local runs;
#   forced_choice_share — the model picked purchase / not purchase via API.
LOGPROB_METHOD = "logprob_p_yes_binary"
FORCED_CHOICE_METHOD = "forced_choice_share"

# Family display order and fixed colors are defined in figures_style; this
# ordering is used for figure panels.
FAMILY_ORDER = ("Qwen", "Gemma", "Granite", "OpenAI", "NVIDIA", "Meta-Muse", "GLM", "Other")

RUN_ROOT_NAME = "results/unblinding"

# One entry per model: canonical id -> everything the pipeline needs.
# model_id aligns with the TASK-2030 metadata DRAFT (ids re-aligned to the
# canonical ids from research R1YESNO-V2 ALIASES.md).
MODELS: dict[str, dict] = {
    "gpt-oss-20b": dict(
        display_name="GPT-OSS-20B", short_name="GPT-OSS-20B", family="OpenAI",
        generation="GPT-OSS", architecture="MoE", total_params_b=21.0,
        active_params_b=3.6, local_or_api="local", quantization="mxfp4",
        run_dir="R1-YESNO-20260912T003134", safe_dir="openai_gpt-oss-20b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/openai/gpt-oss-20b",
        notes="21B total / 3.6B active; 32 experts, 4 active/token; native MXFP4 MoE weights; served MXFP4 GGUF",
    ),
    "gemma-4-26b-a4b": dict(
        display_name="Gemma-4-26B-A4B", short_name="Gemma-4-26B-A4B", family="Gemma",
        generation="Gemma-4", architecture="MoE", total_params_b=25.2,
        active_params_b=3.8, local_or_api="local", quantization="q8_0",
        run_dir="R1-YESNO-20260912T003134", safe_dir="google_gemma-4-26b-a4b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/google/gemma-4-26B-A4B",
        notes="25.2B total / 3.8B active; 128 experts; served the -it checkpoint Q8_0 GGUF although the experiment id lacks -it",
    ),
    "gemma-4-31b-it-qat": dict(
        display_name="Gemma-4-31B (QAT)", short_name="Gemma-4-31B", family="Gemma",
        generation="Gemma-4", architecture="dense", total_params_b=30.7,
        active_params_b=30.7, local_or_api="local", quantization="qat_q4_0",
        run_dir="R1-YESNO-GEMMA31B-20260917T120236", safe_dir="google_gemma-4-31b-it-qat",
        # The 2026-09-18 in-place retry left the frozen demographics_unblinded
        # file damaged (25 cells dropped, 1,198 persona slots double-written),
        # so this leg is read from the repaired sidecar instead (task 2035;
        # merge rule and counts documented in the sidecar's .provenance.md).
        # Path is relative to the results root. The frozen run dir is untouched.
        leg_overrides={"demographics_unblinded": Path(
            "R1-YESNO-ANALYSIS-V2/derived/gemma31b_120236_demographics_unblinded_repaired.jsonl")},
        run_provenance="R1-YESNO-GEMMA31B-20260917T120236 + repaired sidecar",
        method=LOGPROB_METHOD,
        metadata_source="https://huggingface.co/google/gemma-4-31B-it-qat-q4_0-unquantized",
        notes="31B dense; QAT Q4_0; demographics_unblinded read from repaired sidecar (blinded leg row-partial); served gemma-4-31B-it-QAT-Q4_0.gguf",
    ),
    "gemma-4-12b-it-qat": dict(
        display_name="Gemma-4-12B (QAT)", short_name="Gemma-4-12B", family="Gemma",
        generation="Gemma-4", architecture="dense", total_params_b=12.0,
        active_params_b=12.0, local_or_api="local", quantization="qat_q4_0",
        run_dir="R1-YESNO-NEWBATCH-20260918T000738", safe_dir="google_gemma-4-12b-it-qat",
        method=LOGPROB_METHOD,
        metadata_source="https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-unquantized",
        notes="12B dense (card 11.95B); QAT Q4_0; served gemma-4-12B-it-QAT-Q4_0.gguf",
    ),
    "qwen3.8-27b": dict(
        display_name="Qwen3.8-27B", short_name="Qwen3.8-27B", family="Qwen",
        generation="Qwen3.8", architecture="dense", total_params_b=27.0,
        active_params_b=27.0, local_or_api="local", quantization="q4_k_m",
        run_dir="R1-YESNO-20260912T003134", safe_dir="qwen_qwen3.8-27b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/Qwen/Qwen3.8-27B",
        notes="27B dense; served Q4_K_M GGUF",
    ),
    # Architecture/params are user-provided (2026-09-18): MoE, ~95B active,
    # total undisclosed. The run-provenance phrases that used to live in
    # `notes` (partial legs, temperatures) are recorded in the run dirs and
    # DATA_INVENTORY; the CSV row now carries the user-provided facts only.
    "qwen3.8-max-0902": dict(
        display_name="Qwen3.8-Max", short_name="Qwen3.8-Max", family="Qwen",
        generation="Qwen3.8", architecture="MoE", total_params_b=None,
        active_params_b=95.0, local_or_api="api", quantization="unknown",
        run_dir="R1-API-QWEN38MAX-20260915T051942", safe_dir="qwen_qwen3.8-max-0902",
        method=FORCED_CHOICE_METHOD,
        metadata_source="user-provided (2026-09-18); official card undisclosed",
        notes="user asserts MoE ~95B active; treat as approximate",
    ),
    "qwen3.6-27b-dense": dict(
        display_name="Qwen3.6-27B", short_name="Qwen3.6-27B-dense", family="Qwen",
        generation="Qwen3.6", architecture="dense", total_params_b=27.0,
        active_params_b=27.0, local_or_api="local", quantization="q4_k_m",
        run_dir="R1-YESNO-QWEN36D-20260916T231053", safe_dir="qwen_qwen3.6-27b-dense",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/Qwen/Qwen3.6-27B",
        notes="27B dense; experiment id carries -dense suffix, HF repo does not; served Q4_K_M GGUF",
    ),
    "qwen3.6-35b-a3b": dict(
        display_name="Qwen3.6-35B-A3B", short_name="Qwen3.6-35B-A3B", family="Qwen",
        generation="Qwen3.6", architecture="MoE", total_params_b=35.0,
        active_params_b=3.0, local_or_api="local", quantization="q8_0",
        run_dir="R1-YESNO-QWENEXT-20260915T012431", safe_dir="qwen_qwen3.6-35b-a3b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/Qwen/Qwen3.6-35B-A3B",
        notes="35B total / 3B active; 256 experts, 8 routed + 1 shared; hybrid DeltaNet+attention; served Q8_0 GGUF",
    ),
    "qwen3.6-35b-a3b-uncensored": dict(
        display_name="Qwen3.6-35B-A3B Uncensored (HauhauCS)", short_name="Qwen3.6-35B-UC",
        family="Qwen", generation="Qwen3.6", architecture="MoE", total_params_b=35.0,
        active_params_b=3.0, local_or_api="local", quantization="q6_k_p",
        run_dir="R1-YESNO-QWENEXT-20260915T012431",
        safe_dir="qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive",
        method=LOGPROB_METHOD,
        metadata_source="https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive",
        notes="community uncensored derivative of Qwen3.6-35B-A3B (params inherited from base card); GGUF-only Q6_K_P",
    ),
    "qwen3-32b": dict(
        display_name="Qwen3-32B", short_name="Qwen3-32B", family="Qwen",
        generation="Qwen3", architecture="dense", total_params_b=32.8,
        active_params_b=32.8, local_or_api="local", quantization="q4_k_m",
        run_dir="R1-YESNO-NEWBATCH-20260918T000738", safe_dir="qwen_qwen3-32b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/Qwen/Qwen3-32B",
        notes="32.8B dense (non-embedding 31.2B); served Q4_K_M GGUF",
    ),
    "qwen3-4b": dict(
        display_name="Qwen3-4B (Instruct-2507)", short_name="Qwen3-4B", family="Qwen",
        generation="Qwen3", architecture="dense", total_params_b=4.0,
        active_params_b=4.0, local_or_api="local", quantization="q8_0",
        run_dir="R1-YESNO-QWENEXT-20260915T012431", safe_dir="qwen3-4b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507",
        notes="4.0B dense; registry maps experiment id qwen/qwen3-4b to the Instruct-2507 non-thinking variant; served Q8_0 GGUF",
    ),
    "granite-4.1-8b": dict(
        display_name="Granite-4.1-8B", short_name="Granite-4.1-8B", family="Granite",
        generation="Granite-4.1", architecture="dense", total_params_b=8.0,
        active_params_b=8.0, local_or_api="local", quantization="q4_k_m",
        run_dir="R1-YESNO-NEWBATCH-20260918T000738", safe_dir="ibm_granite-4.1-8b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/ibm-granite/granite-4.1-8b",
        notes="8B dense decoder-only (GQA/RoPE/SwiGLU); served Q4_K_M GGUF",
    ),
    "granite-4.1-30b": dict(
        display_name="Granite-4.1-30B", short_name="Granite-4.1-30B", family="Granite",
        generation="Granite-4.1", architecture="dense", total_params_b=30.0,
        active_params_b=30.0, local_or_api="local", quantization="q4_k_m",
        run_dir="R1-YESNO-NEWBATCH-20260918T000738", safe_dir="ibm_granite-4.1-30b",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/ibm-granite/granite-4.1-30b",
        notes="30B dense (NOT an A3B MoE; the hybrid Mamba line is Granite-4.0-H, a different line); served Q4_K_M GGUF",
    ),
    "nemotron-cascade-2-30b-a3b": dict(
        display_name="Nemotron Cascade 2 30B-A3B", short_name="Nemotron-30B-A3B", family="NVIDIA",
        generation="Nemotron-Cascade-2", architecture="MoE", total_params_b=30.0,
        active_params_b=3.0, local_or_api="local", quantization="q8_0",
        run_dir="R1-YESNO-20260912T003134", safe_dir="nvidia_nemotron-cascade-2-30b-a3b",
        method=LOGPROB_METHOD,
        metadata_source="https://huggingface.co/nvidia/Nemotron-Cascade-2-30B-A3B",
        notes="30B total / 3B active; hybrid Mamba-2/attention/MoE (nemotron_h); served bartowski Q8_0 GGUF",
    ),
    "muse-glimmer": dict(
        display_name="Muse Glimmer", short_name="Muse-Glimmer-30B", family="Meta-Muse",
        generation="Muse-Glimmer", architecture="dense", total_params_b=29.6,
        active_params_b=29.6, local_or_api="local", quantization="q4_k_m",
        run_dir="R1-YESNO-20260912T003134", safe_dir="meta_muse-glimmer",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/meta-models/Muse-Glimmer-30B",
        notes="dense causal transformer + perception encoder, ~29.6B incl. encoder; distilled from Muse Spark; served Q4_K_M GGUF",
    ),
    "glm-4.7-flash": dict(
        display_name="GLM-4.7-Flash", short_name="GLM-4.7-Flash", family="GLM",
        generation="GLM-4.7", architecture="MoE", total_params_b=30.0,
        active_params_b=3.0, local_or_api="local", quantization="q8_0",
        run_dir="R1-YESNO-QWENEXT-GLM-20260915T063042", safe_dir="glm_glm-4.7-flash",
        method=LOGPROB_METHOD, metadata_source="https://huggingface.co/zai-org/GLM-4.7-Flash",
        notes="30B-A3B MoE (64 routed + 1 shared experts, 4 active/token); experiment id glm/glm-4.7-flash; served Q8_0 GGUF",
    ),
}

# Run dirs referenced by the registry (for path checks and unknown scanning).
REGISTERED_RUN_DIRS = sorted({info["run_dir"] for info in MODELS.values()})

EXPECTED_FULL_CELLS = 440       # 40 products x 11 price levels (0..200%)
EXPECTED_PRIMARY_CELLS = 400    # 40 products x 10 price levels (20..200%)
EXPECTED_DEMOG_RECORDS = 8_800  # 440 cells x 20 personas
EXPECTED_NONE_RECORDS = 440     # 440 cells x 1 draw


def model_dir(results_root: Path, canonical_id: str) -> Path:
    """Return the answer folder of one model inside a results root."""
    info = MODELS[canonical_id]
    return results_root / info["run_dir"] / info["safe_dir"]


def verify_registry_paths(results_root: Path) -> None:
    """Raise FileNotFoundError if any registered answer folder is missing."""
    missing: list[str] = []
    for canonical_id in MODELS:
        path = model_dir(results_root, canonical_id)
        if not path.is_dir():
            missing.append(str(path))
    if missing:
        raise FileNotFoundError(f"registered model folders missing on disk: {missing}")


def scan_unregistered(results_root: Path) -> list[str]:
    """Report everything on disk the registry does not know about.

    Checks two things: model folders inside the registered run dirs that no
    registry entry points at, and run-level folders in the results root that
    are not registered run dirs. Returns human-readable report lines; an
    empty list means the registry covers everything found.
    """
    lines: list[str] = []
    registered_models = {info["safe_dir"] for info in MODELS.values()}
    for run_name in REGISTERED_RUN_DIRS:
        run_path = results_root / run_name
        if not run_path.is_dir():
            continue
        for child in sorted(run_path.iterdir()):
            if child.is_dir() and child.name not in registered_models and child.name != "pools":
                lines.append(
                    f"UNREGISTERED model folder inside {run_name}: {child.name} "
                    "(not used; registry additions need orchestrator sign-off)"
                )
    known_top = set(REGISTERED_RUN_DIRS)
    for child in sorted(results_root.iterdir()):
        if child.is_dir() and child.name not in known_top:
            lines.append(
                f"run-level dir not in registry: {child.name} "
                "(superseded/exploratory per DATA_INVENTORY; not used)"
            )
    return lines
