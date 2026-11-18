/** Render the real routes (list pane + map layers) at a URL, against a stubbed API. Page tests
 * use this so they exercise routing, the auth gate and the generated client together. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import type { MeOut } from "../api/generated";
import { AuthGate } from "../auth/AuthGate";
import { BaseMap } from "../map/BaseMap";
import { MapLayers } from "../map/MapLayers";
import { ListRoutes } from "../pages/routes";
import { ME, type Route, stubFetch } from "./fetch";

/** Shows the current URL, so tests can assert navigation and filter changes. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

export function renderAt(url: string, routes: Route[], me: MeOut = ME as MeOut) {
  const fetchMock = stubFetch([{ path: "/api/v1/me", body: me }, ...routes]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <AuthGate>
          <ListRoutes />
          <BaseMap>
            <MapLayers />
          </BaseMap>
          <LocationProbe />
        </AuthGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { fetchMock, client, ...view };
}

/** Requests the page made, as "METHOD /path?query" strings (the /me probe left out). */
export function requests(fetchMock: ReturnType<typeof stubFetch>): string[] {
  return fetchMock.mock.calls
    .map(([input, init]) => {
      const url = new URL(String(input), "http://localhost");
      return `${(init?.method ?? "GET").toUpperCase()} ${url.pathname}${url.search}`;
    })
    .filter((line) => line !== "GET /api/v1/me");
}

/** The JSON body of the last request to `method path`. */
export function lastBody(fetchMock: ReturnType<typeof stubFetch>, method: string, path: string) {
  const call = [...fetchMock.mock.calls].reverse().find(([input, init]) => {
    const url = new URL(String(input), "http://localhost");
    return url.pathname === path && (init?.method ?? "GET").toUpperCase() === method;
  });
  return call?.[1]?.body ? JSON.parse(String(call[1].body)) : undefined;
}
