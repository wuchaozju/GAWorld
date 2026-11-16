// frontend/api/backendClient.ts
import axios from "axios";
import { useAuthStore } from "../store/auth";
import { getApiBase } from "./base";
import { getApiLanguage } from "./i18nUtils";

export const API_BASE_URL = getApiBase().replace(/\/+$/, "");

// 统一导出的 axios 客户端
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: false,
});

// 请求里自动加 Authorization 头
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  config.headers = (config.headers ?? {}) as any;
  if (token) {
    (config.headers as any).Authorization = `Bearer ${token}`;
  }
  (config.headers as any)['X-Language'] = getApiLanguage();
  return config;
});

// 401 时自动用 refresh_token 刷新
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error;

    if (response?.status === 401 && !(config as any).__isRetryRequest) {
      const refreshToken = useAuthStore.getState().refreshToken;
      if (refreshToken) {
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

          (config as any).__isRetryRequest = true;
          config.headers = config.headers ?? {};
          (config.headers as any).Authorization = `Bearer ${data.access_token}`;

          return apiClient(config);
        } catch {
          useAuthStore.getState().clearSession();
        }
      }
    }

    return Promise.reject(error);
  },
);
