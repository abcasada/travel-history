import { apiFetch } from "../api/client";
import { stubFetch } from "../test/fetch";
import {
  isRecheckResponse,
  RECHECK_DETAIL,
  RECHECK_MIN_INTERVAL_MS,
  recheckRedirecting,
  redirectForRecheck,
  resetRecheckForTests,
} from "./recheck";

test("only the re-check sentence on a 401 counts", () => {
  expect(isRecheckResponse(401, { detail: RECHECK_DETAIL })).toBe(true);
  expect(isRecheckResponse(401, { detail: "authentication required" })).toBe(false);
  expect(isRecheckResponse(403, { detail: RECHECK_DETAIL })).toBe(false);
  expect(isRecheckResponse(401, undefined)).toBe(false);
  expect(isRecheckResponse(401, RECHECK_DETAIL)).toBe(false);
});

test("redirects to sign-in with the current page as next, keeping query and hash", () => {
  window.history.replaceState(null, "", "/app/trips/7?tab=legs#map");
  const navigate = vi.fn();
  expect(redirectForRecheck({ navigate })).toBe(true);
  expect(navigate).toHaveBeenCalledWith(
    `/auth/login?next=${encodeURIComponent("/app/trips/7?tab=legs#map")}`,
  );
  expect(recheckRedirecting()).toBe(true);
  window.history.replaceState(null, "", "/");
});

test("at most one automatic redirect per minute in a tab", () => {
  const navigate = vi.fn();
  let now = 1_000_000;
  const clock = () => now;
  expect(redirectForRecheck({ navigate, now: clock })).toBe(true);
  // The page came back from the provider (a fresh page load) and got another re-check 401.
  resetRecheckForTests(() => {});
  now += RECHECK_MIN_INTERVAL_MS - 1;
  expect(redirectForRecheck({ navigate, now: clock })).toBe(false);
  expect(recheckRedirecting()).toBe(false);
  expect(navigate).toHaveBeenCalledTimes(1);
  now += 1;
  expect(redirectForRecheck({ navigate, now: clock })).toBe(true);
  expect(navigate).toHaveBeenCalledTimes(2);
});

test("a clock that went backwards doesn't block the redirect", () => {
  window.sessionStorage.setItem("travel.recheckRedirectAt", String(Date.now() + 3_600_000));
  const navigate = vi.fn();
  expect(redirectForRecheck({ navigate })).toBe(true);
});

test("without session storage there is no guard, so no automatic redirect", () => {
  const navigate = vi.fn();
  const storage = () => {
    throw new DOMException("blocked", "SecurityError");
  };
  expect(redirectForRecheck({ navigate, storage })).toBe(false);
  expect(navigate).not.toHaveBeenCalled();
});

test("apiFetch redirects on the re-check 401 only, once, and still throws", async () => {
  const navigate = vi.fn();
  resetRecheckForTests(navigate);
  stubFetch([
    { path: "/api/v1/me", status: 401, body: { detail: "authentication required" } },
    { path: "/api/v1/trips", status: 401, body: { detail: RECHECK_DETAIL } },
  ]);
  await expect(apiFetch("/api/v1/me")).rejects.toMatchObject({ status: 401 });
  expect(navigate).not.toHaveBeenCalled();
  await expect(apiFetch("/api/v1/trips")).rejects.toMatchObject({ status: 401 });
  await expect(apiFetch("/api/v1/trips")).rejects.toMatchObject({ status: 401 });
  expect(navigate).toHaveBeenCalledTimes(1);
});
