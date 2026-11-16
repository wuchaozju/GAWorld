// src/api/base.ts
export function getApiBase(): string {
  const configured = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  if (configured) {
    return configured;
  }

  const baseUrl = String(import.meta.env.BASE_URL || "/").trim();
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;

  return normalizedBase && normalizedBase !== "/"
    ? `${normalizedBase}/api`
    : "/api";
}
