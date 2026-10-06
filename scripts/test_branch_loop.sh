#!/usr/bin/env bash
set -euo pipefail

TEST_BRANCH="${TEST_BRANCH:-Dev}"
TEST_REMOTE_BRANCH="${TEST_REMOTE_BRANCH:-$TEST_BRANCH}"
TEST_INTERVAL_SECONDS="${TEST_INTERVAL_SECONDS:-300}"
LOG_DIR="${LOG_DIR:-output/test-logs}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$LOG_DIR"

run_checks() {
  echo "[test-loop] $(date '+%F %T') branch=$TEST_BRANCH remote=$TEST_REMOTE_BRANCH"
  # A worktree's .git is a file; never switch the production checkout for tests.
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if ! git diff --quiet || ! git diff --cached --quiet; then
      echo "[test-loop] tracked changes present; refusing to switch or test a mixed tree"
      return 1
    fi
    git fetch origin "$TEST_REMOTE_BRANCH" || return 1
    git switch "$TEST_BRANCH" || return 1
    git merge --ff-only "origin/$TEST_REMOTE_BRANCH" || return 1
  else
    echo "[test-loop] no Git checkout; testing local files"
  fi
  "$PYTHON_BIN" -m pytest
}

while true; do
  stamp="$(date '+%Y%m%d-%H%M%S')"
  log_path="$LOG_DIR/pytest-$stamp.log"
  run_checks > "$log_path" 2>&1 || true
  ln -sfn "$(basename "$log_path")" "$LOG_DIR/latest.log"
  sleep "$TEST_INTERVAL_SECONDS"
done
