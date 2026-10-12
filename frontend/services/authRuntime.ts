/**
 * This file handles small auth network jobs for the app shell.
 * pingAuthenticatedSession checks whether the current access token still works.
 * refreshSessionTokens asks the backend for a fresh access token pair.
 */

import { getApiBase } from "./base";

export interface TokenRefreshResponse {
  access_token: string;
  refresh_token: string;
}

const API_BASE_URL = getApiBase().replace(/\/+$/, "");

export async function pingAuthenticatedSession(accessToken: string): Promise<Response> {
  return fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export async function refreshSessionTokens(refreshToken: string): Promise<TokenRefreshResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/token/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    throw new Error(`Token refresh failed: ${response.status}`);
  }

  return response.json() as Promise<TokenRefreshResponse>;
}
