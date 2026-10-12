#!/usr/bin/env bash
# Env config for running fos with Google Gemini.
# Usage:
#   export GEMINI_API_KEY="<YOUR_GOOGLE_AI_STUDIO_API_KEY>"   # REQUIRED
#   # Optionally override defaults below before sourcing
#   # export GEMINI_MODEL="gemini-2.0-flash"  # or gemini-2.0-flash-exp
#   # export GEMINI_TEMPERATURE="0.7"
#   # export GEMINI_MAX_TOKENS="65536"
#   # export GEMINI_TOP_P="1.0"
#   #
#   # Then source and run:
#   #   source fos/scripts/env.gemini.sh
#   #   python3 -m fos.scripts.run_basic_scenes
#
# Notes:
# - Set GEMINI_API_KEY in your shell (do not hardcode secrets in this file).
# - The script sets sensible defaults; adjust as needed.

# Select Gemini dialect for the CLI script
export LLM_DIALECT="gemini"

# Model and generation parameters (can be overridden by pre-set env)
export GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.0-flash}"
export GEMINI_TEMPERATURE="${GEMINI_TEMPERATURE:-0.7}"
export GEMINI_MAX_TOKENS="${GEMINI_MAX_TOKENS:-65536}"
export GEMINI_TOP_P="${GEMINI_TOP_P:-1.0}"

# Gentle reminder if API key is missing
if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "[env.gemini] Warning: GEMINI_API_KEY is not set. Export it before running." >&2
fi

echo "[env.gemini] Configured for Gemini (model=${GEMINI_MODEL})."
