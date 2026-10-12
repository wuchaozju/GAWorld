# This file holds every fixed knob of the twin2k6 study in one place: the
# 15 local models that run it, the two shipped data files (survey questions
# and human benchmark numbers), how many personas answer, and the inference
# settings copied from the proven R1 pipeline (scan window, temperature,
# top-k size, probability floor) plus the study's own thresholds (the
# 0.80 branch-mass flag and the at-most-50-records fsync promise). There
# are no functions here — only named constants so every other module and
# every test reads the same numbers from one source.

from pathlib import Path

# The proven R1 scoring pipeline already defines the one-in-a-million
# visibility floor for top-k entries; reuse it verbatim instead of copying
# the number (import works because twin2k6 is only ever imported with the
# repo's scripts/ folder on the import path).
from logprob_scoring import FOLD_PROBABILITY_FLOOR

# The study's name, used in run folders and output summaries.
STUDY_NAME = "TWIN2K_UNBLINDING_LOGPROBS_6TASKS"

# The repo root, found by walking up from this file (scripts/twin2k6/).
REPO_ROOT = Path(__file__).resolve().parents[2]

# The two shipped data files this whole study is built on. They are verbatim
# research deliveries (see their _provenance keys) and must never be edited.
STIMULI_PATH = REPO_ROOT / "data" / "configs" / "twin2k6_stimuli.json"
BENCHMARKS_PATH = REPO_ROOT / "data" / "configs" / "twin2k6_benchmarks.json"

# The study's 15 models, in the pinned run order: exactly the local models
# of the R1 registry (scripts/r1yesno_v2/registry.py, local_or_api="local").
# The one API model (qwen3.8-max-0902) is deliberately excluded.
MODELS = [
    "gpt-oss-20b",
    "gemma-4-26b-a4b",
    "gemma-4-31b-it-qat",
    "gemma-4-12b-it-qat",
    "qwen3.8-27b",
    "qwen3.6-27b-dense",
    "qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored",
    "qwen3-32b",
    "qwen3-4b",
    "granite-4.1-8b",
    "granite-4.1-30b",
    "nemotron-cascade-2-30b-a3b",
    "muse-glimmer",
    "glm-4.7-flash",
]

# The two blinding arms, in run order: with and without the randomization
# note in the system prompt.
BLINDINGS = ("blinded", "unblinded")

# One shared pool of 100 personas (ids 0-99); every model answers the same
# pool so model differences are never persona differences.
PERSONA_COUNT = 100

# Inference knobs copied from the proven R1 first-token pipeline:
#   SCAN_TOKENS — the short generation window that lets the parser walk past
#                 control tokens to the first real answer token;
#   TEMPERATURE — the paper's fixed sampling temperature;
#   TOP_K       — how many top logprobs to request, big enough that all
#                 21 answer-letter spellings of the widest scale fit;
#   PROBABILITY_FLOOR — top-k entries below one in a million are sampler
#                 noise and never count as an answer (reused from R1).
SCAN_TOKENS = 8
TEMPERATURE = 1.0
TOP_K = 100
PROBABILITY_FLOOR = FOLD_PROBABILITY_FLOOR  # 1e-6, same number as R1

# A combined letter mass strictly below 0.80 is flagged "diffuse" — this
# study is stricter than R1's 0.60 because up to 21 letters share the mass.
LOW_BRANCH_MASS_THRESHOLD = 0.80

# Durability promise: the records file is force-synced to disk at least
# this often, so a crash can lose at most 50 finished records.
FSYNC_EVERY = 50

# The design seed shared by every run of this study.
SEED = 42

# Where the local model server and its model manager live (same defaults
# as every R1 run: llama-server on 8080, the manager control API on 8081).
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_MANAGER_URL = "http://127.0.0.1:8081"
