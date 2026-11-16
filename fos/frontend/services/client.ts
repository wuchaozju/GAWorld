// frontend/api/client.ts

import axios from "axios";
import { useAuthStore } from "../store/auth";
import { getApiBase } from "./base";
import { getApiLanguage } from "./i18nUtils";

/**
 * 统一的后端基础 URL（例如 http://localhost:8000/api）
 */
export const API_BASE_URL = getApiBase().replace(/\/+$/, "");

/**
 * 旧前端使用的 axios 客户端，给 Login/Register/Admin/Providers 等用
 */
export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/`,
});

// Track token refresh state to prevent race conditions
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value?: any) => void;
  reject: (reason?: any) => void;
}> = [];

const processQueue = (error: any | null, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

async function refreshAccessToken(): Promise<string> {
  if (isRefreshing) {
    return await new Promise<string>((resolve, reject) => {
      failedQueue.push({ resolve, reject });
    });
  }

  isRefreshing = true;
  const refreshToken = useAuthStore.getState().refreshToken;

  if (!refreshToken) {
    processQueue(new Error("No refresh token available"), null);
    useAuthStore.getState().clearSession();
    isRefreshing = false;
    throw new Error("No refresh token available");
  }

  try {
    const refreshResponse = await axios.post(
      `${API_BASE_URL}/auth/token/refresh`,
      { refresh_token: refreshToken },
    );
    const data = refreshResponse.data as {
      access_token: string;
      refresh_token: string;
    };

    useAuthStore.getState().updateTokens(
      data.access_token,
      data.refresh_token,
    );

    processQueue(null, data.access_token);
    return data.access_token;
  } catch (refreshError) {
    processQueue(refreshError, null);
    const currentToken = useAuthStore.getState().accessToken;
    if (!currentToken) {
      useAuthStore.getState().clearSession();
    }
    throw refreshError;
  } finally {
    isRefreshing = false;
  }
}

async function authFetch(
  url: string,
  init: RequestInit,
  token?: string,
  retry = true,
): Promise<Response> {
  const effectiveToken = token ?? useAuthStore.getState().accessToken ?? undefined;
  const headers = new Headers(init.headers ?? {});
  if (effectiveToken) {
    headers.set("Authorization", `Bearer ${effectiveToken}`);
  }
  headers.set('X-Language', getApiLanguage());

  const response = await fetch(url, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status !== 401 || !retry) {
    return response;
  }

  const refreshedToken = await refreshAccessToken();
  const retryHeaders = new Headers(init.headers ?? {});
  retryHeaders.set("Authorization", `Bearer ${refreshedToken}`);

  return await fetch(url, {
    ...init,
    headers: retryHeaders,
    credentials: "include",
  });
}

// ---- 拦截器：自动带上 access token，并处理 401 刷新 ----
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  config.headers = (config.headers ?? {}) as any;
  if (token) {
    (config.headers as any).Authorization = `Bearer ${token}`;
  }
  (config.headers as any)['X-Language'] = getApiLanguage();
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error;
    const originalRequest = config;

    if (response?.status === 401 && originalRequest && !(originalRequest as any).__isRetryRequest) {
      try {
        const refreshedToken = await refreshAccessToken();
        (originalRequest as any).__isRetryRequest = true;
        originalRequest.headers = (originalRequest.headers ?? {}) as any;
        (originalRequest.headers as any).Authorization = `Bearer ${refreshedToken}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  },
);

// ---------------------------------------------------------------------
// 下面是新前端用的轻量 HTTP 工具（保留原有写法，避免其它文件改动）
// ---------------------------------------------------------------------

export function buildUrl(base: string, path: string): string {
  const b = base.replace(/\/$/, "");
  const p = path.replace(/^\//, "");
  return `${b}/${p}`;
}

export async function httpGet<T>(
  base: string,
  path: string,
  token?: string,
): Promise<T> {
  const url = buildUrl(base, path);
  const res = await authFetch(url, {
    method: "GET",
  }, token);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export async function httpPost<T>(
  base: string,
  path: string,
  body?: any,
  token?: string,
): Promise<T> {
  const url = buildUrl(base, path);
  const res = await authFetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: body != null ? JSON.stringify(body) : undefined,
  }, token);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export async function httpDelete<T>(
  base: string,
  path: string,
  token?: string,
): Promise<T> {
  const url = buildUrl(base, path);
  const res = await authFetch(url, {
    method: "DELETE",
  }, token);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as unknown as T);
}

/**
 * 方便只用当前后端地址的简单封装（新代码里如果有用到 apiGet/apiPost 也还能工作）
 */
export function apiGet<T>(path: string, token?: string): Promise<T> {
  return httpGet<T>(API_BASE_URL, path, token);
}

export function apiPost<T>(path: string, body?: any, token?: string): Promise<T> {
  return httpPost<T>(API_BASE_URL, path, body, token);
}

export function apiDelete<T>(path: string, token?: string): Promise<T> {
  return httpDelete<T>(API_BASE_URL, path, token);
}
