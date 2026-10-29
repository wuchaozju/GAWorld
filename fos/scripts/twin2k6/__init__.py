# This folder holds the TWIN2K_UNBLINDING_LOGPROBS_6TASKS study package:
# the six Twin2K survey questions are asked to 15 local language models,
# each once with and once without the "which version was randomized" note,
# and the first answer token's letter probabilities are scored and compared
# against the human benchmark numbers. Import it as `twin2k6.<module>` with
# the repo's scripts/ folder on the import path (same convention as the
# other launch scripts). The sub-modules are:
#   config      — the study's fixed knobs (models, files, thresholds)
#   experiments — the six experiments, their arms and answer-letter scales
#   prompts     — builds the exact system and user prompt texts
#   scoring     — turns one top-logprob list into letter probabilities
#   cells       — the 48,000 (model, persona, arm, blinding) cells + resume
#   analyze     — arm means, contrasts, errors, unblinding gain, CSVs
