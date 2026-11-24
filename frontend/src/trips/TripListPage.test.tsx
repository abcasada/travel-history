import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ME } from "../test/fetch";
import { renderAt, requests } from "../test/render";
import { EMPTY_MAP, makeTrip } from "../test/trips";

const LISTS = [
  {
    path: "/api/v1/purposes",
    body: [
      { id: 2, name: "Vacation", default_visibility: "participants", sort: 1, archived: false },
    ],
  },
  { path: "/api/v1/tags", body: [{ id: 5, name: "lakes", color: "", trip_count: 1 }] },
  { path: "/api/v1/trips/map", body: EMPTY_MAP },
];

test("the map home lists trips with their dates, purpose and tags", async () => {
  const shared = makeTrip({
    id: 11,
    title: "Synthetic family visit",
    is_owner: false,
    owner: { id: 3, display_name: "Synthetic Relative" },
    tags: [
      { id: 5, name: "lakes", color: "", author: { id: 1, display_name: "x" }, by_owner: true },
    ],
  });
  renderAt("/", [
    ...LISTS,
    { path: "/api/v1/trips", body: { count: 2, items: [makeTrip(), shared] } },
  ]);
  expect(await screen.findByRole("heading", { name: "Your trips" })).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /Synthetic lake weekend/ })).toHaveAttribute(
    "href",
    "/trips/10",
  );
  expect(screen.getByText("by Synthetic Relative")).toBeInTheDocument();
  expect(screen.getAllByText("#lakes").length).toBeGreaterThan(0);
  expect(screen.getByText("2 trips")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "New trip" })).toHaveAttribute("href", "/trips/new");
});

test("filters go into the URL and the list and map requests (repeated for any-of)", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", [
    ...LISTS,
    { path: "/api/v1/trips", body: { count: 0, items: [] } },
  ]);
  await screen.findByText(/No trips yet/);
  await user.click(screen.getByRole("button", { name: "Drive" }));
  await user.click(screen.getByRole("button", { name: "Flight" }));
  await user.click(await screen.findByRole("button", { name: "#lakes" }));
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent("/trips?tag=5&mode=drive&mode=flight"),
  );
  await waitFor(() =>
    expect(requests(fetchMock)).toContain(
      "GET /api/v1/trips?tag=5&mode=drive&mode=flight&limit=200",
    ),
  );
  expect(requests(fetchMock)).toContain("GET /api/v1/trips/map?tag=5&mode=drive&mode=flight");
  expect(await screen.findByText("No trips match these filters.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/trips$/));
});

test("only in map view narrows the list but not the map", async () => {
  const user = userEvent.setup();
  const { useMapStore } = await import("../map/store");
  useMapStore.getState().setBbox("-98,37,-96,39");
  const { fetchMock } = renderAt("/trips", [
    ...LISTS,
    { path: "/api/v1/trips", body: { count: 0, items: [] } },
  ]);
  await user.click(await screen.findByLabelText("Only in map view"));
  await waitFor(() =>
    expect(requests(fetchMock)).toContain("GET /api/v1/trips?bbox=-98%2C37%2C-96%2C39&limit=200"),
  );
  expect(requests(fetchMock).filter((r) => r.includes("/trips/map?bbox"))).toEqual([]);
  useMapStore.getState().setBbox(null);
});

test("viewers don't get a New trip button", async () => {
  renderAt("/trips", [...LISTS, { path: "/api/v1/trips", body: { count: 0, items: [] } }], {
    ...ME,
    role: "viewer",
  });
  await screen.findByText(/No trips yet/);
  expect(screen.queryByRole("link", { name: "New trip" })).not.toBeInTheDocument();
});

test("the trips layer draws the map payload on trip pages, not on History", async () => {
  const map = {
    trips: [],
    truncated: false,
    stops: [{ id: 1, trip_id: 10, kind: "visit", name: "A", lon: -97, lat: 38 }],
    legs: [
      {
        id: 2,
        trip_id: 10,
        sequence: 1,
        mode: "drive",
        routed: false,
        coordinates: [
          [-97, 38],
          [-96, 39],
        ],
      },
    ],
  };
  renderAt("/trips", [
    ...LISTS.slice(0, 2),
    { path: "/api/v1/trips/map", body: map },
    { path: "/api/v1/trips", body: { count: 0, items: [] } },
  ]);
  await waitFor(() =>
    expect(screen.getByTestId("source-trip-legs")).toHaveAttribute("data-features", "1"),
  );
  expect(screen.getByTestId("source-trip-stops")).toHaveAttribute("data-features", "1");
});

test("the status filter goes into the URL and the API as TripStatus", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", [
    ...LISTS,
    { path: "/api/v1/trips", body: { count: 0, items: [] } },
  ]);
  await screen.findByText(/No trips yet/);
  await user.selectOptions(screen.getByLabelText("Status"), "candidate");
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent("/trips?status=candidate"),
  );
  await waitFor(() =>
    expect(requests(fetchMock)).toContain("GET /api/v1/trips?status=candidate&limit=200"),
  );
  expect(requests(fetchMock)).toContain("GET /api/v1/trips/map?status=candidate");
});
