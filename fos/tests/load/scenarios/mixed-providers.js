/**
 * Mixed LLM provider load test: 10 users on Ollama, 10 on cloud API.
 * Simulates the actual launch scenario with presenter (local) and audience (API).
 *
 * NOTE: This test requires simulations configured with real LLM providers.
 * The mock-based helpers won't trigger real LLM calls. For a real test,
 * modify createSimulation() to use your actual provider configurations.
 *
 * Run: k6 run -e BASE_URL=http://your-server:8090 tests/load/scenarios/mixed-providers.js
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";
import { authenticate, createSimulation, advanceChain, checkHealth, cleanupAllLoadUserSims } from "../lib/helpers.js";

const createSimDuration = new Trend("create_simulation_duration", true);
const advanceDuration = new Trend("advance_chain_duration", true);
const errorCount = new Counter("errors");

export const options = {
  stages: [
    { duration: "40s", target: 20 },
    { duration: "60s", target: 20 },
    { duration: "20s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(90)<10000"],
    http_req_failed: ["rate<0.15"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8090";
const API_PREFIX = __ENV.API_PREFIX || "/api";

export function teardown() {
  cleanupAllLoadUserSims(BASE_URL, 20);
}

export default function () {
  const vuId = __VU;
  // First 10 VUs = "local/Ollama" provider, last 10 = "cloud API"
  const provider = vuId <= 10 ? "ollama" : "openai";

  group(`VU ${vuId} (${provider})`, () => {
    const token = authenticate(BASE_URL, `mixed-vu${vuId}@test.com`, "testpass123");

    let sim;
    group("Create Simulation", () => {
      const start = Date.now();
      // Pass the provider so agents use real LLM calls, not mock.
      // NOTE: Requires the server to have Ollama running (for VUs 1-10) and
      // a valid cloud API key configured (for VUs 11-20).
      sim = createSimulation(BASE_URL, token, `Mixed Test VU${vuId} (${provider})`, provider);
      createSimDuration.add(Date.now() - start);
      if (!sim || !sim.id) {
        errorCount.add(1, { tag: provider });
        return;
      }
    });

    if (!sim || !sim.id) return;

    group("Advance Chain", () => {
      const start = Date.now();
      advanceChain(BASE_URL, token, sim.id, 1);
      advanceDuration.add(Date.now() - start);
    });

    sleep(1);
  });
}
