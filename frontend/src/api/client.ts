/**
 * The only way the frontend talks to the backend: same-origin requests with the session cookie,
 * the CSRF token on unsafe methods, and a typed error. Generated API hooks call `apiFetch`.
 */
import { isRecheckResponse, redirectForRecheck } from "../auth/recheck";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`API request failed with status ${status}`);
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function csrfToken(cookies: string = document.cookie): string | undefined {
  for (const part of cookies.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === "csrftoken") return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (UNSAFE.has(method)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRFToken", token);
  }
  const response = await fetch(url, { ...options, method, headers, credentials: "same-origin" });
  const text = await response.text();
  const body: unknown = text ? JSON.parse(text) : undefined;
  if (!response.ok) {
    // The hourly provider re-check (D-108): sign in again at once, silently while the provider's
    // own session lasts, instead of waiting for the user to find the Sign in screen (D-120).
    if (isRecheckResponse(response.status, body)) redirectForRecheck();
    throw new ApiError(response.status, body);
  }
  return body as T;
}

export function signInUrl(next: string = window.location.pathname + window.location.search) {
  return `/auth/login?next=${encodeURIComponent(next)}`;
}
