#!/usr/bin/env bash
# GAWorld-integrated FOS launcher (docs/FOS_Integration.md §4).
#
# Starts the FOS backend in single-user mode, bound to loopback only, then the
# GAWorld dashboard which proxies /fos/ to it. Standalone FOS deployments
# (fos/README.md, fos/docker-compose.yml) are unaffected: this env is set only
# for the backend process launched here. Open http://127.0.0.1:8766/fos/.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON="${REPO_ROOT}/.venv-fos-integration/bin/python"
if [ ! -x "${PYTHON}" ]; then
    echo "error: ${PYTHON} not found — create the integration venv first" >&2
    exit 1
fi

cleanup() {
    if [ -n "${BACKEND_PID:-}" ] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        kill "${BACKEND_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Terminal 1 equivalent — FOS backend (single-user, loopback only).
# FOS_SINGLE_USER_ALLOW_REMOTE_BIND is deliberately NOT set.
(
    cd "${REPO_ROOT}/fos"
    export PYTHONPATH="${REPO_ROOT}/fos/src${PYTHONPATH:+:${PYTHONPATH}}"
    FOS_SINGLE_USER_MODE=true exec "${PYTHON}" -m uvicorn fos.backend.main:app --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

# Terminal 2 equivalent — GAWorld dashboard (:8766), which serves /fos/.
echo "GAWorld dashboard: http://127.0.0.1:8766/fos/"
cd "${REPO_ROOT}"
python gaworld/apps/dashboard_server.py
