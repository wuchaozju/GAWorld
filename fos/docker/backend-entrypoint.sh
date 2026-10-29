#!/bin/bash
set -e

echo "Starting FOS backend..."

# Best-effort: ensure the embedding model is available, but never block startup.
# Pulling runs in the background; a failed or timed-out pull only logs a warning.
# Base-URL precedence matches get_default_ollama_base_url() in the app:
# FOS_OLLAMA_BASE_URL first, then OLLAMA_BASE_URL, then the in-cluster service.
OLLAMA_URL="${FOS_OLLAMA_BASE_URL:-${OLLAMA_BASE_URL:-http://fos-ollama:11434}}"
OLLAMA_MODEL="${FOS_OLLAMA_EMBED_MODEL:-nomic-embed-text:latest}"

# Untagged model names (e.g. "nomic-embed-text") are reported by /api/tags as
# "<name>:latest", so match by prefix to avoid re-pulling on every start.
if [[ "${OLLAMA_MODEL}" == *:* ]]; then
    MODEL_NEEDLE="\"${OLLAMA_MODEL}\""
else
    MODEL_NEEDLE="\"${OLLAMA_MODEL}:"
fi

(
    if curl -fsS --max-time 10 "${OLLAMA_URL}/api/tags" | grep -q "${MODEL_NEEDLE}"; then
        echo "Embedding model '${OLLAMA_MODEL}' already present."
    else
        echo "Pulling embedding model '${OLLAMA_MODEL}' in background (first run may take a few minutes)..."
        PULL_OUTPUT=$(curl -sS --max-time 1800 -w $'\n%{http_code}' "${OLLAMA_URL}/api/pull" -d "{\"name\":\"${OLLAMA_MODEL}\"}" 2>&1 || true)
        PULL_CODE=$(printf '%s\n' "$PULL_OUTPUT" | tail -n 1)
        PULL_BODY=$(printf '%s\n' "$PULL_OUTPUT" | sed '$d')
        if [[ "$PULL_CODE" == "200" ]]; then
            echo "Embedding model '${OLLAMA_MODEL}' pulled successfully."
        else
            echo "WARNING: could not pull '${OLLAMA_MODEL}' (HTTP ${PULL_CODE}): ${PULL_BODY}"
            echo "         Uploads will fail until pulled manually: docker exec fos-ollama ollama pull ${OLLAMA_MODEL}"
        fi
    fi
) &

echo "Running database migrations..."
alembic upgrade head || echo "Migration skipped or failed"

echo "Starting Uvicorn server..."
exec uvicorn fos.backend.main:app \
    --host ${FOS_BACKEND_HOST:-0.0.0.0} \
    --port ${FOS_BACKEND_PORT:-8000} \
    --root-path ${FOS_BACKEND_ROOT_PATH:-} \
    --workers ${FOS_UVICORN_WORKERS:-1} \
    --timeout-keep-alive 75