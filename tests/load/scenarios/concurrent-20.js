/**
 * Concurrent load test: 20 users running game theory experiments simultaneously.
 * Uses three real experiment scenarios with LLM-backed agents.
 *
 * Scenarios: Prisoner's Dilemma, Public Goods Game, Open Discussion
 * Run: k6 run -e BASE_URL=http://localhost:8000 tests/load/scenarios/concurrent-20.js
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Trend, Counter, Gauge } from "k6/metrics";
import { authenticate, createSimulation, advanceChain, checkHealth, SCENARIOS, cleanupAllLoadUserSims } from "../lib/helpers.js";

const createSimDuration = new Trend("create_simulation_duration", true);
const advanceDuration = new Trend("advance_chain_duration", true);
const errorCount = new Counter("errors");
const activeSims = new Gauge("active_simulations");

const scenarioKeys = Object.keys(SCENARIOS);

export const options = {
  stages: [
    { duration: "40s", target: 20 },  // Ramp to 20 users over 40s (2s stagger)
    { duration: "60s", target: 20 },  // Hold 20 users for 60s
    { duration: "20s", target: 0 },   // Ramp down
  ],
  thresholds: {
    http_req_duration: ["p(90)<300000"],       // 5 min for LLM calls
    http_req_failed: ["rate<0.2"],             // Allow 20% failure under load
    create_simulation_duration: ["p(90)<10000"],
    advance_chain_duration: ["p(90)<300000"],  // 5 min for advance with real LLM
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_PREFIX = __ENV.API_PREFIX || "/api";

export function teardown() {
  cleanupAllLoadUserSims(BASE_URL, 20);
}

export default function () {
  const vuId = __VU;
  // Round-robin scenario selection across VUs
  const scenarioKey = scenarioKeys[(vuId - 1) % scenarioKeys.length];
  const scenario = SCENARIOS[scenarioKey];

  group(`VU ${vuId}: ${scenario.name}`, () => {
    const token = authenticate(BASE_URL);
    if (!token) {
      errorCount.add(1);
      return;
    }

    // Create simulation with this VU's assigned scenario
    let sim;
    group("Create Simulation", () => {
      const start = Date.now();
      sim = createSimulation(BASE_URL, token, `Load Test ${scenario.name} VU${vuId}`, scenario);
      createSimDuration.add(Date.now() - start);
      if (!sim?.id) {
        errorCount.add(1);
      }
    });

    if (!sim?.id) return;

    // Advance tree (1 turn)
    group("Advance Chain", () => {
      const start = Date.now();
      advanceChain(BASE_URL, token, sim.id, 1);
      advanceDuration.add(Date.now() - start);
    });

    // Check health
    const health = checkHealth(BASE_URL);
    if (health) {
      activeSims.add(health.active_simulations || 0);
    }

    sleep(1);
  });
}
