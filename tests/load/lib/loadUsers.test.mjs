/**
 * This file checks that load-test users are picked in a simple, steady way.
 *
 * Each test checks one thing:
 * - test_build_load_user_for_vu_uses_matching_number checks that each VU gets its own user.
 * - test_get_cached_token_logs_in_only_once_per_vu checks that one VU reuses its token.
 * - test_get_cached_token_keeps_tokens_separate_between_vus checks that different VUs do not share tokens.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { buildLoadUserForVu, createVuTokenCache } from "./loadUsers.js";

test("test_build_load_user_for_vu_uses_matching_number", () => {
  assert.deepEqual(buildLoadUserForVu(7), {
    email: "loaduser7@example.com",
    password: "testpass123",
  });
});

test("test_get_cached_token_logs_in_only_once_per_vu", async () => {
  const calls = [];
  const cache = createVuTokenCache((baseUrl, vuId) => {
    calls.push([baseUrl, vuId]);
    return `token-${vuId}`;
  });

  const firstToken = await cache.getTokenForVu("http://example.test", 3);
  const secondToken = await cache.getTokenForVu("http://example.test", 3);

  assert.equal(firstToken, "token-3");
  assert.equal(secondToken, "token-3");
  assert.deepEqual(calls, [["http://example.test", 3]]);
});

test("test_get_cached_token_keeps_tokens_separate_between_vus", async () => {
  const calls = [];
  const cache = createVuTokenCache((baseUrl, vuId) => {
    calls.push([baseUrl, vuId]);
    return `token-${vuId}`;
  });

  const tokenTwo = await cache.getTokenForVu("http://example.test", 2);
  const tokenFive = await cache.getTokenForVu("http://example.test", 5);

  assert.equal(tokenTwo, "token-2");
  assert.equal(tokenFive, "token-5");
  assert.deepEqual(calls, [
    ["http://example.test", 2],
    ["http://example.test", 5],
  ]);
});
