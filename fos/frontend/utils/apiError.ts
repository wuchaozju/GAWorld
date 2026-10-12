/*
This file pulls useful error text out of failed API calls.
getBackendErrorDetail returns only the message sent back by the backend, or null when there is none.
extractApiErrorMessage returns the backend message first, then falls back to the normal error message or a string form.
*/
export function getBackendErrorDetail(e: unknown): string | null {
  const resp = (e as { response?: { data?: unknown } }).response;
  if (resp && resp.data && typeof resp.data === 'object') {
    const data = resp.data as { error?: unknown; detail?: unknown; message?: unknown };
    if (typeof data.error === 'string' && data.error.length > 0) {
      return data.error;
    }
    if (typeof data.detail === 'string' && data.detail.length > 0) {
      return data.detail;
    }
    if (typeof data.message === 'string' && data.message.length > 0) {
      return data.message;
    }
  }
  return null;
}

export function extractApiErrorMessage(e: unknown): string {
  const detail = getBackendErrorDetail(e);
  if (detail !== null) {
    return detail;
  }
  if (e instanceof Error) {
    return e.message;
  }
  return String(e);
}
