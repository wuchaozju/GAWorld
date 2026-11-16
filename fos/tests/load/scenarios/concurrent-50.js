/**
 * Presentation load test: 50 concurrent users with limited heavy simulation work.
 *
 * This models Saturday demo traffic: many people browse and inspect simulations,
 * while only a smaller subset triggers LLM-backed advances at the same time.
 *
 * Run: k6 run -e BASE_URL=http://localhost:8090 tests/load/scenarios/concurrent-50.js
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter, Gauge, Trend } from "k6/metrics";
import {
  authenticate,
  createSimulation,
  advanceChain,
  checkHealth,
  SCENARIOS,
  cleanupAllLoadUserSims,
} from "../lib/helpers.js";

const createSimDuration = new Trend("create_simulation_duration", true);
const advanceDuration = new Trend("advance_chain_duration", true);
const readyFailures = new Counter("readiness_failures");
const badGatewayCount = new Counter("bad_gateway_responses");
const activeSims = new Gauge("active_simulations");
const treeNodes = new Gauge("tree_nodes");

const scenarioKeys = Object.keys(SCENARIOS);

export const options = {
  stages: [
    { duration: "2m", target: 50 },
    { duration: "2h", target: 50 },
    { duration: "2m", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<10000"],
    create_simulation_duration: ["p(95)<15000"],
    advance_chain_duration: ["p(95)<300000"],
    readiness_failures: ["count<5"],
    bad_gateway_responses: ["count==0"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8090";
const API_PREFIX = __ENV.API_PREFIX || "/api";

function recordStatus(response) {
  if (response.status === 502) {
    badGatewayCount.add(1);
  }
}

function checkReadiness() {
  const response = http.get(`${BASE_URL}${API_PREFIX}/health/ready`);
  recordStatus(response);
  const ok = check(response, { "ready ok": (r) => r.status === 200 });
  if (!ok) {
    readyFailures.add(1);
  }
}

export function teardown() {
  cleanupAllLoadUserSims(BASE_URL, 50);
}

export default function () {
  const vuId = __VU;
  const scenario = SCENARIOS[scenarioKeys[(vuId - 1) % scenarioKeys.length]];

  group(`VU ${vuId}: presentation flow`, () => {
    if (vuId % 10 === 1) {
      checkReadiness();
    }

    const token = authenticate(BASE_URL);
    if (!token) {
      return;
    }

    recordStatus(http.get(`${BASE_URL}${API_PREFIX}/scenes`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: "20s",
    }));

    let sim;
    if (vuId % 2 === 0) {
      const start = Date.now();
      sim = createSimulation(BASE_URL, token, `Presentation VU${vuId}`, scenario);
      createSimDuration.add(Date.now() - start);
    }

    if (sim?.id) {
      recordStatus(http.get(`${BASE_URL}${API_PREFIX}/simulations/${sim.id}`, {
        headers: { Authorization: `Bearer ${token}` },
        timeout: "20s",
      }));
      recordStatus(http.get(`${BASE_URL}${API_PREFIX}/simulations/${sim.id}/tree/graph`, {
        headers: { Authorization: `Bearer ${token}` },
        timeout: "20s",
      }));
    }

    if (sim?.id && vuId % 10 === 0) {
      const start = Date.now();
      advanceChain(BASE_URL, token, sim.id, 1);
      advanceDuration.add(Date.now() - start);
    }

    const health = checkHealth(BASE_URL);
    if (health) {
      activeSims.add(health.active_simulations || 0);
      treeNodes.add(health.tree_nodes || 0);
    }

    sleep(2);
  });
}
