import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ME } from "../test/fetch";
import { lastBody, renderAt, requests } from "../test/render";
import { EMPTY_MAP, makeTrip } from "../test/trips";
import { EMPTY_SELECTION, useSelectionStore } from "./selection";
import { PAGE_SIZE } from "./TripListPage";

const TRIPS = [
  makeTrip({ id: 10, title: "Synthetic lake weekend" }),
  makeTrip({ id: 11, title: "Synthetic coast drive" }),
  makeTrip({ id: 12, title: "Synthetic city break" }),
];

const LISTS = [
  {
    path: "/api/v1/purposes",
    body: [
      { id: 2, name: "Vacation", default_visibility: "participants", sort: 1, archived: false },
      { id: 3, name: "Business", default_visibility: "family", sort: 2, archived: false },
      { id: 9, name: "Old", default_visibility: "family", sort: 0, archived: true },
    ],
  },
  { path: "/api/v1/tags", body: [{ id: 5, name: "lakes", color: "", trip_count: 1 }] },
  {
    path: "/api/v1/persons",
    body: [
      {
        id: 4,
        display_name: "Synthetic Cousin",
        visibility: "family",
        is_me: false,
        has_account: false,
        can_edit: true,
      },
    ],
  },
  { path: "/api/v1/trips/map", body: EMPTY_MAP },
  { path: "/api/v1/trips", body: { count: 3, items: TRIPS } },
];

const BULK_OK = { method: "POST", path: "/api/v1/trips/bulk", body: { count: 2, items: [] } };

beforeEach(() => useSelectionStore.setState({ ...EMPTY_SELECTION, fitRequest: 0 }));

const row = (title: string) => screen.getByRole("link", { name: new RegExp(title) }).closest("li");

async function ready() {
  await screen.findByRole("link", { name: /Synthetic lake weekend/ });
}

test("j/k move the cursor, x selects, Shift+j extends, and the map highlights the selection", async () => {
  const user = userEvent.setup();
  renderAt("/trips", [...LISTS, BULK_OK]);
  await ready();
  await user.keyboard("j");
  expect(row("Synthetic lake weekend")).toHaveAttribute("aria-current", "true");
  await user.keyboard("jk");
  expect(row("Synthetic lake weekend")).toHaveAttribute("aria-current", "true");
  await user.keyboard("x");
  expect(screen.getByRole("checkbox", { name: "Select Synthetic lake weekend" })).toBeChecked();
  await user.keyboard("{Shift>}J{/Shift}");
  const bar = screen.getByRole("region", { name: "Selected trips" });
  expect(within(bar).getByText("2 selected")).toBeInTheDocument();
  expect(row("Synthetic coast drive")).toHaveAttribute("aria-current", "true");
  const paint = JSON.parse(screen.getByTestId("layer-trip-legs").dataset.paint ?? "{}");
  expect(JSON.stringify(paint["line-width"])).toContain("[10,11]");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("region", { name: "Selected trips" })).not.toBeInTheDocument();
});

test("Enter opens the cursor's trip", async () => {
  const user = userEvent.setup();
  renderAt("/trips", LISTS);
  await ready();
  await user.keyboard("jj{Enter}");
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/trips/11"));
});

test("e opens the cursor's trip editor", async () => {
  const user = userEvent.setup();
  renderAt("/trips", LISTS);
  await ready();
  await user.keyboard("je");
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/trips/10/edit"));
});

test("* then a selects every listed trip, * then n none", async () => {
  const user = userEvent.setup();
  renderAt("/trips", LISTS);
  await ready();
  await user.keyboard("*a");
  expect(screen.getByText("3 selected")).toBeInTheDocument();
  await user.keyboard("*n");
  expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
});

test("t tags the selection with one of your tags in one bulk request", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", [...LISTS, BULK_OK]);
  await ready();
  await user.click(screen.getByRole("checkbox", { name: "Select Synthetic lake weekend" }));
  await user.click(screen.getByRole("checkbox", { name: "Select Synthetic city break" }));
  await user.keyboard("t");
  await user.selectOptions(await screen.findByLabelText("Your tag"), "5");
  await user.click(screen.getByRole("button", { name: "Add tag" }));
  expect(await screen.findByText("Tag added: 2 trips updated.")).toBeInTheDocument();
  expect(lastBody(fetchMock, "POST", "/api/v1/trips/bulk")).toEqual({
    trip_ids: [10, 12],
    add_tag_ids: [5],
  });
});

test("a new tag name creates the tag first, then tags the trips", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", [
    ...LISTS,
    BULK_OK,
    {
      method: "POST",
      path: "/api/v1/tags",
      status: 201,
      body: { id: 8, name: "roadtrip", color: "", trip_count: 0 },
    },
  ]);
  await ready();
  await user.keyboard("jx");
  await user.click(screen.getByRole("button", { name: "Tag" }));
  await user.type(await screen.findByLabelText("New tag name"), "roadtrip");
  await user.click(screen.getByRole("button", { name: "Add tag" }));
  await screen.findByText("Tag added: 1 trip updated.");
  expect(lastBody(fetchMock, "POST", "/api/v1/tags")).toEqual({ name: "roadtrip" });
  expect(lastBody(fetchMock, "POST", "/api/v1/trips/bulk")).toEqual({
    trip_ids: [10],
    add_tag_ids: [8],
  });
});

test("a refused bulk change lists each refused trip with the reason", async () => {
  const user = userEvent.setup();
  renderAt("/trips", [
    ...LISTS,
    {
      method: "POST",
      path: "/api/v1/trips/bulk",
      status: 403,
      body: {
        detail: "Some trips can't take this change.",
        refused: [{ trip_id: 11, reason: "Only the owner can change the purpose." }],
      },
    },
  ]);
  await ready();
  await user.keyboard("*a");
  await user.click(screen.getByRole("button", { name: "Purpose" }));
  await user.selectOptions(await screen.findByLabelText("Purpose"), "3");
  await user.click(screen.getByRole("button", { name: "Set purpose" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Nothing was changed. 1 trip can't take this change:");
  expect(alert).toHaveTextContent("Synthetic coast drive: Only the owner can change the purpose.");
});

test("a digit sets that purpose on the cursor's trip when nothing is selected", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", [...LISTS, BULK_OK]);
  await ready();
  await user.keyboard("jj2");
  await screen.findByText("Purpose set to Business: 1 trip updated.");
  // Archived purposes take no digit: 1 is Vacation, 2 is Business.
  expect(lastBody(fetchMock, "POST", "/api/v1/trips/bulk")).toEqual({
    trip_ids: [11],
    purpose_id: 3,
  });
});

test("people and visibility go to every selected trip", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", [...LISTS, BULK_OK]);
  await ready();
  await user.keyboard("j{Shift>}J{/Shift}p");
  const bar = screen.getByRole("region", { name: "Selected trips" });
  await user.selectOptions(await within(bar).findByLabelText("Person"), "4");
  await user.click(screen.getByRole("button", { name: "Remove from trips" }));
  await screen.findByText("Person removed: 2 trips updated.");
  expect(lastBody(fetchMock, "POST", "/api/v1/trips/bulk")).toEqual({
    trip_ids: [10, 11],
    remove_person_ids: [4],
  });
  await user.click(screen.getByRole("button", { name: "Visibility" }));
  await user.selectOptions(within(bar).getByLabelText("Visibility"), "family");
  await user.click(screen.getByRole("button", { name: "Set visibility" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/bulk")).toEqual({
      trip_ids: [10, 11],
      visibility: "family",
    }),
  );
});

test("viewers can't select trips for bulk changes", async () => {
  const user = userEvent.setup();
  renderAt("/trips", LISTS, { ...ME, role: "viewer" });
  await ready();
  expect(screen.queryByRole("checkbox", { name: /^Select / })).not.toBeInTheDocument();
  await user.keyboard("jx");
  expect(screen.queryByRole("region", { name: "Selected trips" })).not.toBeInTheDocument();
});

test("person and visibility filters go into the URL and the requests", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", LISTS);
  await ready();
  await user.selectOptions(screen.getByLabelText("Person"), "4");
  await user.selectOptions(screen.getByLabelText("Visibility"), "private");
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent("/trips?person=4&visibility=private"),
  );
  await waitFor(() =>
    expect(requests(fetchMock)).toContain(
      `GET /api/v1/trips?person=4&visibility=private&limit=${PAGE_SIZE}`,
    ),
  );
  expect(requests(fetchMock)).toContain("GET /api/v1/trips/map?person=4&visibility=private");
});

test("a filter that drops selected trips drops them from the selection", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips", LISTS);
  await ready();
  await user.keyboard("*a");
  expect(screen.getByText("3 selected")).toBeInTheDocument();
  const base = fetchMock.getMockImplementation();
  fetchMock.mockImplementation(async (input, init) =>
    String(input).startsWith("/api/v1/trips?mode=drive")
      ? Response.json({ count: 1, items: [TRIPS[0]] })
      : (base as NonNullable<typeof base>)(input, init),
  );
  await user.click(screen.getByRole("button", { name: "Drive" }));
  expect(await screen.findByText("1 selected")).toBeInTheDocument();
});

test("more than a page of trips loads with Show more and keeps the count", async () => {
  const user = userEvent.setup();
  const first = Array.from({ length: PAGE_SIZE }, (_, i) =>
    makeTrip({ id: 1000 + i, title: `Synthetic trip ${i}` }),
  );
  const last = makeTrip({ id: 5000, title: "Synthetic oldest trip" });
  const { fetchMock } = renderAt("/trips", [
    ...LISTS.slice(0, 4),
    { path: "/api/v1/trips", body: { count: PAGE_SIZE + 1, items: first } },
  ]);
  const base = fetchMock.getMockImplementation();
  fetchMock.mockImplementation(async (input, init) =>
    String(input).includes("offset=200")
      ? Response.json({ count: PAGE_SIZE + 1, items: [last] })
      : (base as NonNullable<typeof base>)(input, init),
  );
  expect(await screen.findByText(`${PAGE_SIZE + 1} trips (newest 200 shown)`)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Show 1 more" }));
  expect(await screen.findByRole("link", { name: /Synthetic oldest trip/ })).toBeInTheDocument();
  expect(screen.getByText(`${PAGE_SIZE + 1} trips`)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Show \d+ more/ })).not.toBeInTheDocument();
  expect(requests(fetchMock)).toContain(`GET /api/v1/trips?limit=${PAGE_SIZE}&offset=200`);
});
