/**
 * This file picks simple load-test users and remembers one token per VU.
 *
 * Each function does one small job:
 * - buildLoadUserForVu picks the email and password for one VU number.
 * - createVuTokenCache remembers a token for each VU after the first login.
 */

const LOAD_TEST_USER_PASSWORD = "testpass123";

/**
 * Pick the load-test login details for one VU number.
 *
 * @param {number} vuId - The k6 virtual user number.
 * @returns {{email: string, password: string}}
 */
export function buildLoadUserForVu(vuId) {
  return {
    email: `loaduser${vuId}@example.com`,
    password: LOAD_TEST_USER_PASSWORD,
  };
}

/**
 * Build a tiny token store that keeps one token for each VU.
 *
 * @param {(baseUrl: string, vuId: number) => string|null} loginForVu - Logs in one VU when needed.
 * @returns {{getTokenForVu(baseUrl: string, vuId: number): string|null}}
 */
export function createVuTokenCache(loginForVu) {
  const tokensByVu = new Map();

  return {
    getTokenForVu(baseUrl, vuId) {
      if (tokensByVu.has(vuId)) {
        return tokensByVu.get(vuId);
      }

      const token = loginForVu(baseUrl, vuId);
      if (token) {
        tokensByVu.set(vuId, token);
      }
      return token;
    },
  };
}
