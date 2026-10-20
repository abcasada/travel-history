import { stubFetch } from "../test/fetch";
import { ApiError, apiFetch, csrfToken } from "./client";

test("reads the CSRF token from cookies", () => {
  expect(csrfToken("a=1; csrftoken=abc%3D; b=2")).toBe("abc=");
  expect(csrfToken("a=1")).toBeUndefined();
});

test("sends the CSRF token on unsafe methods only", async () => {
  // biome-ignore lint/suspicious/noDocumentCookie: the test sets the cookie the client reads
  document.cookie = "csrftoken=tok123";
  const fetchMock = stubFetch([
    { path: "/api/v1/x", body: { ok: true } },
    { method: "POST", path: "/api/v1/x", body: { ok: true } },
  ]);
  await apiFetch("/api/v1/x");
  await apiFetch("/api/v1/x", { method: "POST" });
  const [, getInit] = fetchMock.mock.calls[0] as [string, RequestInit];
  const [, postInit] = fetchMock.mock.calls[1] as [string, RequestInit];
  expect(new Headers(getInit.headers).get("X-CSRFToken")).toBeNull();
  expect(new Headers(postInit.headers).get("X-CSRFToken")).toBe("tok123");
  expect(postInit.credentials).toBe("same-origin");
});

test("throws a typed error with the status", async () => {
  stubFetch([{ path: "/api/v1/me", status: 401, body: { detail: "authentication required" } }]);
  await expect(apiFetch("/api/v1/me")).rejects.toMatchObject({ status: 401 });
  await expect(apiFetch("/api/v1/me")).rejects.toBeInstanceOf(ApiError);
});
