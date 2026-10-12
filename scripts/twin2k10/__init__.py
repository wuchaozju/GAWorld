# This folder holds the TWIN2K_UNBLINDING_LOGPROBS_10TASKS study package:
# the ten Twin2K survey experiments (23 questions) are put to 15 local
# language models, each once with and once without the "which version was
# randomized" note; every answer — choice letter or rating/estimate
# digit — is scored from the first answer token's label probabilities,
# and results are compared against the human benchmark numbers. Import
# it as `twin2k10.<module>` with the repo's scripts/ folder on the
# import path (same convention as the other launch scripts). The
# sub-modules are:
#   config      — the study's fixed knobs (models, files, thresholds)
#   registry    — the model address book (manager ids, GGUF paths)
#   experiments — the ten experiments, their arms and first-token items
#   prompts     — builds the exact system and per-item user prompt texts
#   scoring     — label folding (letters and digits) + parse_numeric
#   cells       — the 57,000 (model, persona, arm, blinding) cells + resume
#   legexec     — executes one cell end to end into its record
#   preflight   — the pure stop-or-proceed verdict + report writer
#   runner      — the single-command launch (auto-preflight, resume)
