#!/usr/bin/env bash
set -euo pipefail

TEST_BRANCH="${TEST_BRANCH:-Dev}"
TEST_INTERVAL_SECONDS="${TEST_INTERVAL_SECONDS:-300}"
LOG_DIR="${LOG_DIR:-output/test-logs}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$LOG_DIR"

while true; do
  stamp="$(date '+%Y%m%d-%H%M%S')"
  log_path="$LOG_DIR/pytest-$stamp.log"
  {
    echo "[test-loop] $(date '+%F %T') branch=$TEST_BRANCH"
    if [ -d .git ]; then
      echo "[test-loop] git remote: $(git remote get-url origin 2>/dev/null || echo none)"
      if git fetch origin; then
        git switch "$TEST_BRANCH"
        git pull --ff-only origin "$TEST_BRANCH"
      else
        echo "[test-loop] git fetch failed; check GitHub repository access for this server key"
        echo "[test-loop] testing currently deployed working tree instead"
      fi
    else
      echo "[test-loop] .git not found; testing deployed working tree"
    fi
    "$PYTHON_BIN" -m pytest
  } > "$log_path" 2>&1 || true
  ln -sfn "$(basename "$log_path")" "$LOG_DIR/latest.log"
  sleep "$TEST_INTERVAL_SECONDS"
done
