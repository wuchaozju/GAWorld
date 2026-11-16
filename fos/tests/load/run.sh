#!/bin/bash
# Run all k6 load test scenarios against the FOS platform.
#
# Usage:
#   ./tests/load/run.sh --target http://your-server:8090
#   ./tests/load/run.sh --target http://localhost:8090 --scenario baseline
#
# Prerequisites:
#   k6 installed (https://k6.io/docs/get-started/installation/)
#
# Options:
#   --target URL        Target server URL (required)
#   --scenario NAME     Run specific scenario: baseline, concurrent-20, concurrent-50,
#                       mixed-providers, or all (default: all)
#   --out DIR          Output directory for reports (default: tests/load/reports)

set -euo pipefail

TARGET=""
SCENARIO="all"
API_PREFIX="${FOS_API_PREFIX:-/api}"
OUT_DIR="tests/load/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

while [[ $# -gt 0 ]]; do
  case $1 in
    --target) TARGET="$2"; shift 2 ;;
    --scenario) SCENARIO="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [ -z "$TARGET" ]; then
  echo "Error: --target is required"
  echo "Usage: $0 --target http://your-server:8090 [--scenario baseline|concurrent-20|concurrent-50|mixed-providers|all]"
  echo ""
  echo "  Set FOS_API_PREFIX to override the API path (default: /api)."
  echo "  For production deployments use: FOS_API_PREFIX=/css/fos/api $0 --target http://server:8090"
  exit 1
fi

if ! command -v k6 &> /dev/null; then
  echo "Error: k6 is not installed. Install from https://k6.io/docs/get-started/installation/"
  exit 1
fi

# Verify server is reachable
echo "Checking server connectivity at $TARGET ..."
if ! python3 -c "import urllib.request; urllib.request.urlopen('${TARGET}${API_PREFIX}/health/live')" 2>/dev/null; then
  echo "Error: Could not reach $TARGET${API_PREFIX}/health/live"
  echo "Make sure your server is running and the --target URL is correct."
  exit 1
fi
echo "Server reachable. Make sure loaduser1 through loaduser50 already exist before running concurrent tests."
echo ""

mkdir -p "$OUT_DIR"

run_scenario() {
  local name=$1
  local script=$2
  local report="${OUT_DIR}/${TIMESTAMP}_${name}.json"

  echo "=========================================="
  echo "Running: $name"
  echo "Target:  $TARGET"
  echo "Report:  $report"
  echo "=========================================="

  k6 run \
    --env BASE_URL="$TARGET" \
    --env API_PREFIX="$API_PREFIX" \
    --out json="$report" \
    --summary-export="${OUT_DIR}/${TIMESTAMP}_${name}_summary.json" \
    "$script" || true

  echo ""
  echo "$name complete. Summary:"
  if [ -f "${OUT_DIR}/${TIMESTAMP}_${name}_summary.json" ]; then
    python3 -c "
import json, sys
with open('${OUT_DIR}/${TIMESTAMP}_${name}_summary.json') as f:
    s = json.load(f)
m = s.get('metrics', {})
http = m.get('http_req_duration', {}).get('values', {})
print(f\"  HTTP p50: {http.get('med', 0):.0f}ms  p90: {http.get('p(90)', 0):.0f}ms  p95: {http.get('p(95)', 0):.0f}ms\")
print(f\"  HTTP failed: {m.get('http_req_failed', {}).get('values', {}).get('rate', 0)*100:.1f}%\")
print(f\"  Iterations: {m.get('iterations', {}).get('values', {}).get('count', 0)}\")
" 2>/dev/null || echo "  (summary parse failed)"
  fi
  echo ""
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

case "$SCENARIO" in
  baseline)
    run_scenario "baseline" "$SCRIPT_DIR/scenarios/baseline.js"
    ;;
  concurrent-20)
    run_scenario "concurrent-20" "$SCRIPT_DIR/scenarios/concurrent-20.js"
    ;;
  concurrent-50)
    run_scenario "concurrent-50" "$SCRIPT_DIR/scenarios/concurrent-50.js"
    ;;
  mixed-providers)
    run_scenario "mixed-providers" "$SCRIPT_DIR/scenarios/mixed-providers.js"
    ;;
  all)
    run_scenario "baseline" "$SCRIPT_DIR/scenarios/baseline.js"
    run_scenario "concurrent-20" "$SCRIPT_DIR/scenarios/concurrent-20.js"
    run_scenario "concurrent-50" "$SCRIPT_DIR/scenarios/concurrent-50.js"
    run_scenario "mixed-providers" "$SCRIPT_DIR/scenarios/mixed-providers.js"
    ;;
  *)
    echo "Unknown scenario: $SCENARIO"
    exit 1
    ;;
esac

echo "=========================================="
echo "All tests complete. Reports in: $OUT_DIR"
echo ""
echo "Next steps:"
echo "  1. Check Docker logs for timing entries:"
echo "     docker logs fos-app 2>&1 | grep '\[LLM\]\|\[SIM\]\|\[WS\]\|\[DB\]'"
echo ""
echo "  2. Compare baseline vs concurrent metrics"
echo ""
echo "  3. Follow the analysis playbook in the design doc"
echo "=========================================="
