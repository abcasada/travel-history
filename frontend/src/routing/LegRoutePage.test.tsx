import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ME } from "../test/fetch";
import { lastBody, renderAt, requests } from "../test/render";
import { EMPTY_MAP, makeDetail, makeLeg, makeStop } from "../test/trips";

const MAP = { path: "/api/v1/trips/map", body: EMPTY_MAP };

test("a leg without a route says so and draws nothing extra", async () => {
  renderAt("/trips/10/legs/200/route", [
    MAP,
    { path: "/api/v1/legs/200", body: makeLeg({ origin_label: "Synthville" }) },
    { path: "/api/v1/legs/200/routes", body: [] },
  ]);
  expect(
    await screen.findByRole("heading", { name: /Drive: Synthville → end/ }),
  ).toBeInTheDocument();
  expect(await screen.findByText("No route saved yet.")).toBeInTheDocument();
  expect(screen.queryByTestId("source-leg-route")).not.toBeInTheDocument();
});

test("the current route version is listed and drawn on the map", async () => {
  const route = {
    id: 9,
    leg_id: 200,
    version: 2,
    kind: "manual",
    engine: "",
    engine_version: "",
    engine_data_date: null,
    attribution: "",
    produced_at: "2024-05-04T10:00:00Z",
    created_by: { id: 1, display_name: "Synthetic Member" },
    length_m: 12345,
    note: "",
    is_current: true,
  };
  renderAt("/trips/10/legs/200/route", [
    MAP,
    { path: "/api/v1/legs/200", body: makeLeg({ current_route_id: 9 }) },
    { path: "/api/v1/legs/200/routes", body: [route] },
    {
      path: "/api/v1/routes/9",
      body: {
        ...route,
        waypoints: [],
        geometry: {
          type: "MultiLineString",
          coordinates: [
            [
              [-97, 38],
              [-96, 39],
            ],
          ],
        },
      },
    },
  ]);
  expect(await screen.findByText(/Version 2 · manual · 12.3 km/)).toHaveTextContent("(current)");
  await waitFor(() => expect(screen.getByTestId("source-leg-route")).toBeInTheDocument());
});

test("a leg the caller can't see is not found", async () => {
  renderAt("/trips/10/legs/5/route", [
    MAP,
    { path: "/api/v1/legs/5", status: 404, body: { detail: "leg not found" } },
  ]);
  expect(
    await screen.findByText("This leg doesn't exist or isn't shared with you."),
  ).toBeInTheDocument();
});

// --- Proposing and saving a route (item 25) -------------------------------------------------

const START = makeStop({
  id: 101,
  place: { id: 501, name: "Synthville", address: "", lon: -97.33, lat: 37.69, country_code: "" },
});
const END = makeStop({
  id: 102,
  place: { id: 502, name: "Fakeburg", address: "", lon: -97.61, lat: 38.84, country_code: "" },
});
const ROAD_LEG = makeLeg({ origin_stop_id: 101, destination_stop_id: 102 });
const TRIP = { path: "/api/v1/trips/10", body: makeDetail({ stops: [START, END] }) };
const PROPOSAL = {
  code: "Ok",
  routes: [
    {
      geometry: {
        type: "LineString",
        coordinates: [
          [-97.33, 37.69],
          [-97.5, 38.2],
          [-97.61, 38.84],
        ],
      },
      distance: 144672,
      duration: 4653,
      legs: [{ distance: 144672, duration: 4653, summary: "" }],
    },
  ],
  waypoints: [],
  provenance: {
    engine: "valhalla",
    engine_version: "3.9.1",
    data_date: "2026-11-18",
    attribution: "Route: Valhalla, data © OpenStreetMap contributors",
    produced_at: "2026-11-18T10:00:00Z",
  },
  cached: false,
};

function routeRoutes(extra: { method?: string; path: string; status?: number; body?: unknown }[]) {
  return [
    MAP,
    TRIP,
    { path: "/api/v1/legs/200", body: ROAD_LEG },
    { path: "/api/v1/legs/200/routes", body: [] },
    ...extra,
  ];
}

test("propose a route, see its provider and attribution, and save it as a version", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt(
    "/trips/10/legs/200/route",
    routeRoutes([
      { method: "POST", path: "/api/v1/routing/route", body: PROPOSAL },
      { method: "POST", path: "/api/v1/legs/200/routes", status: 201, body: {} },
    ]),
  );
  await user.click(await screen.findByRole("button", { name: "Propose a route" }));
  expect(lastBody(fetchMock, "POST", "/api/v1/routing/route")).toEqual({
    waypoints: [
      [-97.33, 37.69],
      [-97.61, 38.84],
    ],
    profile: "auto",
  });
  expect(await screen.findByText("Proposed: 144.7 km, 1 h 18 min")).toBeInTheDocument();
  expect(
    screen.getByText(/Valhalla \(self-hosted\) 3.9.1, road data 2026-11-18/),
  ).toBeInTheDocument();
  expect(screen.getByTestId("route-attribution")).toHaveTextContent("© OpenStreetMap");
  // The line and the two waypoints are drawn on the map.
  expect(screen.getByTestId("source-leg-proposal")).toHaveAttribute("data-features", "3");

  await user.type(screen.getByLabelText("Note for this version"), "via the interstate");
  await user.click(screen.getByRole("button", { name: "Save as a new version" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/legs/200/routes")).toEqual({
      waypoints: [
        [-97.33, 37.69],
        [-97.61, 38.84],
      ],
      note: "via the interstate",
    }),
  );
  await waitFor(() => expect(screen.queryByTestId("source-leg-proposal")).not.toBeInTheDocument());
});

test("routing failures show the server's reason", async () => {
  const user = userEvent.setup();
  renderAt(
    "/trips/10/legs/200/route",
    routeRoutes([
      {
        method: "POST",
        path: "/api/v1/routing/route",
        status: 503,
        body: { detail: "no routing service is available right now" },
      },
    ]),
  );
  await user.click(await screen.findByRole("button", { name: "Propose a route" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "no routing service is available right now",
  );
});

test("a leg without both end stops explains what's missing", async () => {
  const { fetchMock } = renderAt("/trips/10/legs/200/route", [
    MAP,
    TRIP,
    { path: "/api/v1/legs/200", body: makeLeg({ origin_stop_id: 101 }) },
    { path: "/api/v1/legs/200/routes", body: [] },
  ]);
  expect(await screen.findByText(/Give this leg a start and an end stop/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Propose a route" })).not.toBeInTheDocument();
  expect(requests(fetchMock)).not.toContain("POST /api/v1/routing/route");
});

test("flights don't get road routes", async () => {
  renderAt("/trips/10/legs/200/route", [
    MAP,
    TRIP,
    { path: "/api/v1/legs/200", body: { ...ROAD_LEG, mode: "flight" } },
    { path: "/api/v1/legs/200/routes", body: [] },
  ]);
  expect(
    await screen.findByText(/Road routes are for drive, bus and other legs/),
  ).toBeInTheDocument();
});

test("viewers and people who can't edit the leg see versions only", async () => {
  renderAt("/trips/10/legs/200/route", routeRoutes([]), { ...ME, role: "viewer" } as typeof ME);
  expect(await screen.findByText("No route saved yet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Propose a route" })).not.toBeInTheDocument();
});
