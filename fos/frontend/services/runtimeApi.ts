/**
 * This file sends small authenticated requests for store actions.
 * postRuntimeJson sends one signed JSON request and returns the JSON reply.
 */

import { useAuthStore } from "../store/auth";
import { getApiBase } from "./base";
import { getApiLanguage } from "./i18nUtils";

const API_BASE_URL = getApiBase().replace(/\/+$/, "");

function buildHeaders(): Headers {
  const headers = new Headers({
    "Content-Type": "application/json",
    "X-Language": getApiLanguage(),
  });
  const accessToken = useAuthStore.getState().accessToken;
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  return headers;
}

export async function postRuntimeJson<T>(
  path: string,
  body: unknown,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/${path.replace(/^\/+/, "")}`, {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify(body),
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}
