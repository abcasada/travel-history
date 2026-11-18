import { screen, waitFor } from "@testing-library/react";
import { renderAt } from "../test/render";
import { EMPTY_MAP, makeLeg } from "../test/trips";

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
