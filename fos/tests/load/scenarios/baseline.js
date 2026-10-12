/**
 * Baseline load test: single user creates and runs a simulation.
 * Establishes performance baselines for comparison with concurrent tests.
 *
 * Run: k6 run -e BASE_URL=http://localhost:8000 tests/load/scenarios/baseline.js
 */

import http from "k6/http";
import { check, group } from "k6";
import { Trend } from "k6/metrics";
import { authenticate, createSimulation, advanceChain, checkHealth, cleanupAllLoadUserSims } from "../lib/helpers.js";

const createSimDuration = new Trend("create_simulation_duration", true);
const advanceDuration = new Trend("advance_chain_duration", true);

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    http_req_duration: ["p(95)<5000"],
    create_simulation_duration: ["p(95)<3000"],
    advance_chain_duration: ["p(95)<30000"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_PREFIX = __ENV.API_PREFIX || "/api";

export function teardown() {
  cleanupAllLoadUserSims(BASE_URL, 1);
}

export default function () {
  group("Baseline: Single User", () => {
    // Health check
    group("Health Check", () => {
      const health = checkHealth(BASE_URL);
      console.log(`Health: ${JSON.stringify(health)}`);
    });

    // Auth
    const token = authenticate(BASE_URL);
    if (!token) {
      console.error("Auth failed — cannot continue");
      return;
    }

    // Create simulation
    let sim;
    group("Create Simulation", () => {
      const start = Date.now();
      sim = createSimulation(BASE_URL, token, "Baseline Test Sim");
      createSimDuration.add(Date.now() - start);
      console.log(`Created sim: ${sim?.id}`);
    });

    if (!sim?.id) {
      console.error(`Sim creation failed or missing id. Response: ${JSON.stringify(sim)}`);
      return;
    }

    // Advance tree
    group("Advance Chain (1 turn)", () => {
      const start = Date.now();
      advanceChain(BASE_URL, token, sim.id, 1);
      advanceDuration.add(Date.now() - start);
    });

    // Final health check
    group("Final Health", () => {
      const health = checkHealth(BASE_URL);
      console.log(`Final health: active_sims=${health.active_simulations} ws=${health.active_websocket_connections}`);
    });
  });
}
