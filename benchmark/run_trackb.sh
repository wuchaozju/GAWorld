#!/usr/bin/env bash
# Track B controlled pair: does learned avoidance redistribute where people go?
#
# Runs both arms x N seeds with everything isolated per run, then hands the
# directories to benchmark/trackb_spatial.py. See the congestion proposal
# section 16.4 for why each override is there; the two that silently ruin the
# experiment are stateful=false (aversions persist to disk and would leak
# across seeds) and never using --fast-forward (occupancy is recorded per tick).
#
#   PY=/path/to/python N=100 WORKERS=8 bash benchmark/run_trackb.sh [days] [seeds...]
#
# N is the cohort size (residents 1..N) and is NOT optional in spirit: the
# shipped default for CONFIG["agent_ids"] is five residents, and a dashboard
# session can leave it at one. Crowding is occupancy/capacity, so a handful of
# residents cannot crowd anything, no interrupt fires, no aversion accumulates,
# and both arms come out identical for a reason that has nothing to do with the
# hypothesis. Set N to the city's whole population.
#
# WORKERS is concurrency.day_routine_workers. The shipped default is serial
# (concurrency.enabled=false), which measured ~7 LLM calls per resident-tick
# back to back — hours per sim-day at 100 residents. See proposal 16.6.
#
# Defaults: 30 days, seeds 1 2 3, N=100, WORKERS=8.
#
# The six runs go one after another on purpose: they would share the same LLM
# provider anyway, and one log at a time stays readable. Concurrency inside a
# run (WORKERS) is where the speedup is.
set -u
PY="${PY:-python3}"
N="${N:-100}"
WORKERS="${WORKERS:-8}"
DAYS="${1:-30}"
shift 2>/dev/null || true
SEEDS=("$@")
[ ${#SEEDS[@]} -eq 0 ] && SEEDS=(1 2 3)
ROOT="output/trackb"
CACHE="$ROOT/_base_cache"
mkdir -p "$ROOT" "$CACHE"

# Base schedules and action spaces are generated one LLM call per resident, in
# a plain serial loop (generative_city_sim.py:3040 — parallel_map is NOT used
# there), measured at roughly 20s per resident: ~35 min per run at N=100,
# repeated for all six runs. They are cache files under memory_dir, so the
# first run warms them and the rest can start from that copy.
#
# Sharing exactly these two file kinds across arms and seeds is not a
# shortcut that weakens the comparison — it strengthens it. A base schedule is
# pre-treatment: both arms are supposed to start from the same population.
# Everything that the treatment actually touches (env_preferences, episodes,
# the vector db) stays isolated per run.
_seed_cache_into() {  # $1 = the run's memory dir
    mkdir -p "$1"
    cp "$CACHE"/*_schedule.json "$1"/ 2>/dev/null
    cp "$CACHE"/*_actions.json "$1"/ 2>/dev/null
    return 0
}
_harvest_cache_from() {  # $1 = the run's memory dir
    cp "$1"/*_schedule.json "$CACHE"/ 2>/dev/null
    cp "$1"/*_actions.json "$CACHE"/ 2>/dev/null
    return 0
}

for arm in ref trt; do
  for seed in "${SEEDS[@]}"; do
    dir="$ROOT/$arm-s$seed"
    [ -f "$dir/records/spatial.occupancy.jsonl" ] && { echo "skip $arm-s$seed (already has occupancy)"; continue; }
    sp=false; [ "$arm" = trt ] && sp=true
    GAWORLD_CONFIG_OVERRIDES=$("$PY" - "$seed" "$sp" "$dir" "$N" "$WORKERS" <<'PYOV'
import json, sys
seed, sp, out, n, workers = (sys.argv[1], sys.argv[2], sys.argv[3],
                            int(sys.argv[4]), int(sys.argv[5]))
print(json.dumps({
    "random_seed": int(seed),
    "agent_ids": list(range(1, n + 1)),
    # Serial by default, and the dominant stage (daily routine + action-space
    # generation) is one independent LLM call per resident. Cost: with
    # workers > 1 the global random stream is consumed out of order, so a seed
    # no longer reproduces step for step. The judgement here is the separation
    # of two curves against cross-seed spread, which absorbs that; say so in
    # any write-up, and turn it off for anything that must replay exactly.
    "concurrency": {"enabled": True, "day_routine_workers": int(workers)},
    "stateful": False,
    "local_physical": {"record_occupancy": True},
    "spatial_preferences": {"enabled": sp == "true"},
    "records": {"output_dir": f"{out}/records"},
    "run_output_dir": out,
    "memory_dir": f"{out}/memory",
    "log_dir": f"{out}/logs",
    "vector_db_path": f"{out}/memory/vector_db.sqlite",
    "state_output_dir": f"{out}/state",
    "network_output_dir": f"{out}/network",
    "environment_output_dir": f"{out}/environment",
    "visualization": {"enabled": False},
    "distributed": {"enabled": False},
}))
PYOV
) || exit 1
    export GAWORLD_CONFIG_OVERRIDES
    _seed_cache_into "$dir/memory"
    echo "=== $arm-s$seed ($DAYS days, $N residents, $WORKERS workers) $(date '+%H:%M:%S')"
    "$PY" generative_city_sim.py run --sim-days "$DAYS" > "$ROOT/$arm-s$seed.log" 2>&1 \
      || { echo "FAILED $arm-s$seed — tail of log:"; tail -20 "$ROOT/$arm-s$seed.log"; }
    _harvest_cache_from "$dir/memory"
  done
done

echo "=== analysing $(date '+%H:%M:%S')"
ref=(); trt=()
for seed in "${SEEDS[@]}"; do ref+=("$ROOT/ref-s$seed/records"); trt+=("$ROOT/trt-s$seed/records"); done
"$PY" benchmark/trackb_spatial.py --reference "${ref[@]}" --treatment "${trt[@]}"
