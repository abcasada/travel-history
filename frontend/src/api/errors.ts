/**
 * One place that turns API failures into what the UI says (docs/design/frontend-patterns.md,
 * "Errors and permissions"). The backend's rules: 401 signed out, 403 a visible thing the caller
 * may not change, 404 something they can't see (its existence is not revealed), 409 a duplicate,
 * 422 invalid data or a reference they can't use, 429 rate limited.
 */
import { ApiError } from "./client";

export type ErrorKind =
  | "unauthorized"
  | "forbidden"
  | "not-found"
  | "conflict"
  | "invalid"
  | "rate-limited"
  | "server"
  | "network";

export function errorKind(error: unknown): ErrorKind {
  if (!(error instanceof ApiError)) return "network";
  switch (error.status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not-found";
    case 409:
      return "conflict";
    case 400:
    case 422:
      return "invalid";
    case 429:
      return "rate-limited";
    default:
      return "server";
  }
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

function detail(error: unknown): unknown {
  return error instanceof ApiError && typeof error.body === "object" && error.body !== null
    ? (error.body as { detail?: unknown }).detail
    : undefined;
}

/** The server's own sentence (`{"detail": "..."}`), if it sent one. */
export function serverMessage(error: unknown): string | undefined {
  const d = detail(error);
  return typeof d === "string" ? d : undefined;
}

/**
 * Field errors from a Django Ninja validation response (`{"detail": [{loc, msg}]}`), keyed by
 * the last element of `loc` (the field name, e.g. "title"). Forms show these next to fields.
 */
export function fieldErrors(error: unknown): Record<string, string> {
  const d = detail(error);
  if (!Array.isArray(d)) return {};
  const out: Record<string, string> = {};
  for (const item of d as ValidationItem[]) {
    const field = item.loc?.[item.loc.length - 1];
    if (field !== undefined && item.msg && !(String(field) in out)) out[String(field)] = item.msg;
  }
  return out;
}

/** A sentence for the user. `what` names the thing ("trip", "leg") for 404s. */
export function errorMessage(error: unknown, what = "item"): string {
  const kind = errorKind(error);
  switch (kind) {
    case "not-found":
      return `This ${what} doesn't exist or isn't shared with you.`;
    case "forbidden":
      return serverMessage(error) ?? `You can't change this ${what}.`;
    case "unauthorized":
      return "You're signed out. Reload the page to sign in again.";
    case "conflict":
      return serverMessage(error) ?? "That already exists.";
    case "invalid": {
      const message = serverMessage(error);
      if (message) return capitalize(message);
      const fields = Object.entries(fieldErrors(error));
      return fields.length
        ? fields.map(([field, msg]) => `${field}: ${msg}`).join("; ")
        : "Some of the values aren't valid.";
    }
    case "rate-limited":
      return "Too many requests. Wait a moment and try again.";
    case "server":
      return "The server had a problem. Try again shortly.";
    default:
      return "Couldn't reach the server. Check your connection and try again.";
  }
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
