# This file is the twin2k6 study's model address book. The study names its
# 15 models with short ids (config.MODELS, e.g. "gpt-oss-20b"), but the
# model manager that loads and unloads them knows each model by its full
# registry id (e.g. "openai/gpt-oss-20b") and serves it from one fixed GGUF
# file on disk. This file maps the two, and also carries the two per-model
# serving overrides the proven R1 pipeline established: which models need a
# control-token SEQUENCE skipped before the real answer token, and where
# each model's weights live. It is data only — the mapping table was
# transcribed from the manager's own MODEL_REGISTRY
# (~/fos-model-manager/model_manager.py:42) and verified on disk 2026-09 by
# the pipeline research (PIPELINE_MAP.md §2).

from pathlib import Path

# Short study id -> the id the model manager's /models/load endpoint knows,
# transcribed from the manager's MODEL_REGISTRY (one id differs textually
# from the study's short name: the uncensored qwen has no "qwen/" prefix;
# qwen3-4b is registered under exactly its short name, with no org prefix).
MANAGER_MODEL_IDS: dict[str, str] = {
    "gpt-oss-20b": "openai/gpt-oss-20b",
    "gemma-4-26b-a4b": "google/gemma-4-26b-a4b",
    "gemma-4-31b-it-qat": "google/gemma-4-31b-it-qat",
    "gemma-4-12b-it-qat": "google/gemma-4-12b-it-qat",
    "qwen3.8-27b": "qwen/qwen3.8-27b",
    "qwen3.6-27b-dense": "qwen/qwen3.6-27b-dense",
    "qwen3.6-35b-a3b": "qwen/qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored": (
        "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive"
    ),
    "qwen3-32b": "qwen/qwen3-32b",
    "qwen3-4b": "qwen3-4b",
    "granite-4.1-8b": "ibm/granite-4.1-8b",
    "granite-4.1-30b": "ibm/granite-4.1-30b",
    "nemotron-cascade-2-30b-a3b": "nvidia/nemotron-cascade-2-30b-a3b",
    "muse-glimmer": "meta/muse-glimmer",
    "glm-4.7-flash": "glm/glm-4.7-flash",
}

# Manager id -> the GGUF weights file the manager serves it from, verbatim
# from the manager's MODEL_REGISTRY (recorded in manifests for provenance;
# the runner never opens these files itself).
GGUF_PATHS: dict[str, str] = {
    "openai/gpt-oss-20b": (
        "~/.lmstudio/models/lmstudio-community/gpt-oss-20b-GGUF/"
        "gpt-oss-20b-MXFP4.gguf"
    ),
    "google/gemma-4-26b-a4b": (
        "~/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/"
        "gemma-4-26B-A4B-it-Q8_0.gguf"
    ),
    "google/gemma-4-31b-it-qat": (
        "~/.lmstudio/models/lmstudio-community/gemma-4-31B-it-QAT-GGUF/"
        "gemma-4-31B-it-QAT-Q4_0.gguf"
    ),
    "google/gemma-4-12b-it-qat": (
        "~/.lmstudio/models/lmstudio-community/gemma-4-12B-it-QAT-GGUF/"
        "gemma-4-12B-it-QAT-Q4_0.gguf"
    ),
    "qwen/qwen3.8-27b": (
        "~/.lmstudio/models/lmstudio-community/Qwen3.8-27B-GGUF/"
        "Qwen3.8-27B-Q4_K_M.gguf"
    ),
    "qwen/qwen3.6-27b-dense": (
        "~/.lmstudio/models/lmstudio-community/Qwen3.6-27B-GGUF/"
        "Qwen3.6-27B-Q4_K_M.gguf"
    ),
    "qwen/qwen3.6-35b-a3b": (
        "~/.lmstudio/models/lmstudio-community/Qwen3.6-35B-A3B-GGUF/"
        "Qwen3.6-35B-A3B-Q8_0.gguf"
    ),
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive": (
        "~/.lmstudio/models/HauhauCS/"
        "Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/"
        "Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q6_K_P.gguf"
    ),
    "qwen/qwen3-32b": (
        "~/.lmstudio/models/lmstudio-community/Qwen3-32B-GGUF/"
        "Qwen3-32B-Q4_K_M.gguf"
    ),
    "qwen3-4b": (
        "~/.lmstudio/models/lmstudio-community/Qwen3-4B-Instruct-2507-GGUF/"
        "Qwen3-4B-Instruct-2507-Q8_0.gguf"
    ),
    "ibm/granite-4.1-8b": (
        "~/.lmstudio/models/lmstudio-community/granite-4.1-8b-GGUF/"
        "granite-4.1-8b-Q4_K_M.gguf"
    ),
    "ibm/granite-4.1-30b": (
        "~/.lmstudio/models/lmstudio-community/granite-4.1-30b-GGUF/"
        "granite-4.1-30b-Q4_K_M.gguf"
    ),
    "nvidia/nemotron-cascade-2-30b-a3b": (
        "~/.lmstudio/models/bartowski/nvidia_Nemotron-Cascade-2-30B-A3B-GGUF/"
        "nvidia_Nemotron-Cascade-2-30B-A3B-Q8_0.gguf"
    ),
    "meta/muse-glimmer": (
        "~/.lmstudio/models/lmstudio-community/Muse-Glimmer-30B-GGUF/"
        "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"
    ),
    "glm/glm-4.7-flash": (
        "~/.lmstudio/models/lmstudio-community/GLM-4.7-Flash-GGUF/"
        "GLM-4.7-Flash-Q8_0.gguf"
    ),
}

# Manager id -> the control-token SEQUENCE(S) that must be skipped (as one
# block each) before the real answer token, copied verbatim from the R1
# queue's MODEL_CONTROL_SEQUENCES (scripts/launch_queue.py:102). A model
# absent from the map keeps the default-off empty tuple — the same
# "config lives in the map, never a model-name branch in scoring code"
# convention as the R1 queue.
CONTROL_SEQUENCES: dict[str, tuple[tuple[str, ...], ...]] = {
    "google/gemma-4-26b-a4b": (("<|channel>", "thought", "\n", "<channel|>"),),
}


def manager_model_id(model: str) -> str:
    """The model manager's registry id for one short study model id.

    Raises ValueError naming the offender when the short id is not one of
    the study's 15 models (a typo should stop the run, not invent a model).
    """
    try:
        return MANAGER_MODEL_IDS[model]
    except KeyError:
        raise ValueError(
            f"unknown study model {model!r} — not one of the ids the "
            "manager registry maps"
        ) from None


def gguf_path(model: str) -> str:
    """The GGUF weights file of one short study model id (for manifests)."""
    return GGUF_PATHS[manager_model_id(model)]


def control_sequences(model: str) -> tuple[tuple[str, ...], ...]:
    """The control-token sequences to skip for one short study model id.

    Empty tuple for every model without an override (identity behavior).
    """
    return CONTROL_SEQUENCES.get(manager_model_id(model), ())


def safe_model_name(model: str) -> str:
    """One short study model id made safe to use inside a file name.

    Same rule as the R1 pipeline's _safe_model_name: every "/" and space
    becomes an underscore, so leg folders never contain slashes.
    """
    return model.replace("/", "_").replace(" ", "_")


def model_manifest_entries(models: list[str]) -> list[dict[str, str]]:
    """One manifest row per model: short id, manager id, safe name, GGUF."""
    return [
        {
            "model": model,
            "model_id": manager_model_id(model),
            "safe_name": safe_model_name(model),
            "gguf": gguf_path(model),
        }
        for model in models
    ]


def pool_file(run_dir: Path) -> Path:
    """The run's shared persona pool file (the subsample the pool phase writes)."""
    return Path(run_dir) / "pools" / "twin2k_respondent.jsonl"
