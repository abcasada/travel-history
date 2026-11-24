/**
 * The hourly provider re-check (D-108, D-120; docs/design/auth.md §7.2). When the server ends a
 * session because the sign-in provider hasn't vouched for it recently, its 401 carries this exact
 * sentence (backend `travel.accounts.sessions.DUE_DETAIL`). The SPA then goes straight back
 * through sign-in, which Authentik answers without asking while its own session lasts, and the
 * callback returns to the same page. Any other 401 (a real sign-out, an account removed from the
 * group) keeps the Sign in screen.
 *
 * Loop guard: at most one automatic redirect per minute per tab. If the provider's answer doesn't
 * produce a session that lasts (a misconfigured re-check, a clock problem), the second 401 within
 * the minute shows the Sign in screen instead of bouncing forever. Without session storage (a
 * private window that blocks it) there is no guard, so there is no automatic redirect either.
 */
import { signInUrl } from "../api/client";

export const RECHECK_DETAIL =
  "sign in again: the session needs a fresh check with the sign-in provider";
export const RECHECK_MIN_INTERVAL_MS = 60_000;
const STORAGE_KEY = "travel.recheckRedirectAt";

let redirecting = false;
let assign = (url: string) => window.location.assign(url);

/** True when a response is the server's "fresh provider check" 401. */
export function isRecheckResponse(status: number, body: unknown): boolean {
  return (
    status === 401 &&
    typeof body === "object" &&
    body !== null &&
    (body as { detail?: unknown }).detail === RECHECK_DETAIL
  );
}

export type RecheckDeps = {
  now?: () => number;
  storage?: () => Storage;
  navigate?: (url: string) => void;
};

/**
 * Start the sign-in redirect for a re-check 401, unless one already started in this tab within
 * the last minute. Returns whether it redirected.
 */
export function redirectForRecheck(deps: RecheckDeps = {}): boolean {
  const now = (deps.now ?? Date.now)();
  const navigate = deps.navigate ?? assign;
  if (redirecting) return true;
  try {
    const storage = (deps.storage ?? (() => window.sessionStorage))();
    const last = Number(storage.getItem(STORAGE_KEY));
    if (
      Number.isFinite(last) &&
      last > 0 &&
      now - last >= 0 &&
      now - last < RECHECK_MIN_INTERVAL_MS
    ) {
      return false;
    }
    storage.setItem(STORAGE_KEY, String(now));
  } catch {
    return false;
  }
  redirecting = true;
  navigate(signInUrl(window.location.pathname + window.location.search + window.location.hash));
  return true;
}

/** Whether this page is already on its way to sign-in (AuthGate shows a note, not the screen). */
export function recheckRedirecting(): boolean {
  return redirecting;
}

/** Tests only: forget a redirect in progress; `navigate` replaces `location.assign`. */
export function resetRecheckForTests(navigate?: (url: string) => void): void {
  redirecting = false;
  assign = navigate ?? ((url: string) => window.location.assign(url));
}
