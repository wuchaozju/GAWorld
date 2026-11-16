/**
 * Shared helpers for k6 load test scenarios.
 *
 * Provides authentication, simulation creation (with real experiment scenarios),
 * and tree advancement utilities used across all test scenarios.
 *
 * Exports: authenticate, createSimulation, advanceChain, checkHealth, SCENARIOS
 */

import http from "k6/http";
import { check } from "k6";
import { buildLoadUserForVu, createVuTokenCache } from "./loadUsers.js";

const API_PREFIX = __ENV.API_PREFIX || "/api";

// Single shared test account — all VUs log in as this user.
// For load testing purposes this is fine; we're stressing the backend,
// not testing per-user isolation.
const tokenCache = createVuTokenCache(loginForVu);

/**
 * Pre-built experiment scenario configs for load testing.
 * Each uses scene_type "experiment_template" with a specific scenario_id.
 * No llm_config is specified — the server uses the user's configured LLM provider.
 */
export const SCENARIOS = {
  prisoners_dilemma: {
    name: "Prisoner's Dilemma",
    scene_type: "experiment_template",
    scene_config: {
      scenario_id: "prisoners_dilemma",
    },
    agent_config: {
      agents: [
        { name: "Alice", profile: "A rational decision-maker." },
        { name: "Bob", profile: "A strategic thinker." },
      ],
    },
  },

  public_goods: {
    name: "Public Goods Game",
    scene_type: "experiment_template",
    scene_config: {
      scenario_id: "public_goods",
      tokens_per_round: 10,
      multiplier: 1.5,
    },
    agent_config: {
      agents: [
        { name: "Agent-1", profile: "A cooperative participant." },
        { name: "Agent-2", profile: "A strategic participant." },
        { name: "Agent-3", profile: "A cautious participant." },
        { name: "Agent-4", profile: "A competitive participant." },
      ],
    },
  },

  open_discussion: {
    name: "Open Discussion",
    scene_type: "experiment_template",
    scene_config: {
      scenario_id: "open_discussion",
      topic: "What is the best approach to reduce carbon emissions?",
    },
    agent_config: {
      agents: [
        { name: "Alice", profile: "An environmental scientist." },
        { name: "Bob", profile: "An economist focused on market solutions." },
        { name: "Carol", profile: "A policy maker." },
      ],
    },
  },
};

/**
 * Authenticate and return a JWT access token.
 * Uses the shared test account — no registration needed.
 */
export function authenticate(baseUrl) {
  const vuId = Number(globalThis.__VU || 1);
  return tokenCache.getTokenForVu(baseUrl, vuId);
}

/**
 * Log in one VU with its matching load-test account.
 *
 * @param {string} baseUrl - Target server URL
 * @param {number} vuId - The k6 virtual user number
 * @returns {string|null}
 */
function loginForVu(baseUrl, vuId) {
  const user = buildLoadUserForVu(vuId);
  const res = http.post(
    `${baseUrl}${API_PREFIX}/auth/login`,
    JSON.stringify(user),
    { headers: { "Content-Type": "application/json" } }
  );

  const ok = check(res, { "login ok": (r) => r.status === 200 || r.status === 201 });
  if (!ok) {
    console.error(`Login failed for ${user.email}: ${res.status} ${res.body}`);
    return null;
  }

  const body = res.json();
  return body.access_token || body.token || body.data?.access_token || null;
}

/**
 * Create a simulation using one of the pre-built experiment scenarios.
 *
 * @param {string} baseUrl     - Target server URL
 * @param {string} token       - JWT access token
 * @param {string} name        - Simulation name
 * @param {object} scenario    - Scenario config from SCENARIOS (default: prisoners_dilemma)
 */
export function createSimulation(baseUrl, token, name, scenario = SCENARIOS.prisoners_dilemma) {
  const payload = {
    name: name,
    scene_type: scenario.scene_type,
    scene_config: scenario.scene_config,
    agent_config: scenario.agent_config,
  };

  const res = http.post(`${baseUrl}${API_PREFIX}/simulations`, JSON.stringify(payload), {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });

  const ok = check(res, { "create sim ok": (r) => r.status === 201 || r.status === 200 });
  if (!ok) {
    console.error(`Create sim failed: ${res.status} ${res.body}`);
    return null;
  }

  const body = res.json();
  return body.data || body;
}

/**
 * Advance a simulation tree chain from the root node.
 * Timeout is 240s to accommodate real LLM calls.
 */
export function advanceChain(baseUrl, token, simId, turns) {
  const res = http.post(
    `${baseUrl}${API_PREFIX}/simulations/${simId}/tree/advance_chain`,
    JSON.stringify({ parent: 0, turns: turns }),
    {
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      timeout: "240s",
    }
  );

  const ok = check(res, { "advance ok": (r) => r.status === 200 || r.status === 201 });
  if (!ok) {
    console.error(`Advance failed: ${res.status} ${res.body}`);
  }
  return res.json();
}

/**
 * Delete all simulations owned by each load test user.
 *
 * Iterates VU 1 through maxVu, logs in as each loaduser,
 * and deletes all their simulations via the bulk endpoint.
 * Safe to call even if a user has no simulations.
 */
export function cleanupAllLoadUserSims(baseUrl, maxVu) {
  for (let vu = 1; vu <= maxVu; vu++) {
    const user = buildLoadUserForVu(vu);
    const res = http.post(`${baseUrl}${API_PREFIX}/auth/login`, JSON.stringify(user), {
      headers: { "Content-Type": "application/json" },
    });
    if (res.status !== 200 && res.status !== 201) {
      console.error(`Teardown login failed for ${user.email}: ${res.status}`);
      continue;
    }

    const body = res.json();
    const token = body.access_token || body.token || null;
    if (!token) {
      console.error(`Teardown no token for ${user.email}`);
      continue;
    }

    const delRes = http.del(`${baseUrl}${API_PREFIX}/simulations/all`, null, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (delRes.status !== 204) {
      console.error(`Teardown cleanup failed for ${user.email}: ${delRes.status}`);
    }
  }
  console.log(`Teardown: cleaned up simulations for ${maxVu} load users`);
}

/**
 * Check the health endpoint and return metrics.
 */
export function checkHealth(baseUrl) {
  const res = http.get(`${baseUrl}${API_PREFIX}/health`);
  check(res, { "health ok": (r) => r.status === 200 });
  return res.json();
}
