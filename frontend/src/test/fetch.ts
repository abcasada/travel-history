import { vi } from "vitest";

export type Route = { method?: string; path: string; status?: number; body?: unknown };

/** Stub fetch with a small route table; returns the mock to inspect calls. */
export function stubFetch(routes: Route[]) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const route = routes.find(
      (r) => r.path === url.pathname && (r.method ?? "GET").toUpperCase() === method,
    );
    if (!route) return new Response("{}", { status: 404 });
    return new Response(route.body === undefined ? "" : JSON.stringify(route.body), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

export const ME = {
  id: 1,
  email: "member@example.test",
  display_name: "Synthetic Member",
  role: "member",
  person_id: null,
  privacy_notice_ack_at: "2026-10-20T00:00:00Z",
  onboarding_done_at: null,
};
