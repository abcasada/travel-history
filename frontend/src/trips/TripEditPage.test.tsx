import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMapStore } from "../map/store";
import { ME } from "../test/fetch";
import { lastBody, renderAt, requests } from "../test/render";
import { EMPTY_MAP, makeDetail, makeLeg, makeParticipant, makeStop } from "../test/trips";

const COMMON = [
  { path: "/api/v1/trips/map", body: EMPTY_MAP },
  {
    path: "/api/v1/purposes",
    body: [
      { id: 2, name: "Vacation", default_visibility: "participants", sort: 1, archived: false },
    ],
  },
  {
    path: "/api/v1/persons",
    body: [
      {
        id: 7,
        display_name: "Synthetic Parent",
        visibility: "family",
        is_me: false,
        has_account: true,
        can_edit: false,
      },
    ],
  },
];

test("creating a trip checks the fields, then opens its editor", async () => {
  const user = userEvent.setup();
  const created = makeDetail({ id: 42, title: "Synthetic road trip" });
  const { fetchMock } = renderAt("/trips/new", [
    ...COMMON,
    { method: "POST", path: "/api/v1/trips", status: 201, body: created },
    { path: "/api/v1/trips/42", body: created },
  ]);
  await user.click(await screen.findByRole("button", { name: "Create trip" }));
  expect(screen.getByText("Give the trip a title.")).toBeInTheDocument();
  expect(requests(fetchMock).some((r) => r.startsWith("POST"))).toBe(false);

  await user.type(screen.getByLabelText("Title"), "Synthetic road trip");
  await user.type(screen.getByLabelText("Start date"), "2024-06-01");
  await user.clear(screen.getByLabelText("End date"));
  await user.type(screen.getByLabelText("End date"), "2024-05-30");
  await user.click(screen.getByRole("button", { name: "Create trip" }));
  expect(screen.getByText("The end can't be before the start.")).toBeInTheDocument();

  await user.clear(screen.getByLabelText("End date"));
  await user.type(screen.getByLabelText("End date"), "2024-06-04");
  await user.selectOptions(await screen.findByLabelText("Purpose"), "Vacation");
  await user.click(screen.getByRole("button", { name: "Create trip" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/trips/42/edit"));
  // No visibility chosen: the server applies the purpose's default.
  expect(lastBody(fetchMock, "POST", "/api/v1/trips")).toEqual({
    title: "Synthetic road trip",
    start_date: "2024-06-01",
    end_date: "2024-06-04",
    purpose_id: 2,
    notes: "",
  });
  expect(await screen.findByRole("heading", { name: "Edit trip" })).toBeInTheDocument();
});

test("server validation errors show next to their field", async () => {
  const user = userEvent.setup();
  renderAt("/trips/new", [
    ...COMMON,
    {
      method: "POST",
      path: "/api/v1/trips",
      status: 422,
      body: { detail: [{ loc: ["body", "payload", "title"], msg: "Title is too long" }] },
    },
  ]);
  await user.type(await screen.findByLabelText("Title"), "x");
  await user.type(screen.getByLabelText("Start date"), "2024-06-01");
  await user.click(screen.getByRole("button", { name: "Create trip" }));
  expect(await screen.findByText("Title is too long")).toBeInTheDocument();
});

test("a stop placed by typed coordinates or a map click is saved as a new place", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/trips/10/edit", [
    ...COMMON,
    { path: "/api/v1/trips/10", body: makeDetail() },
    { method: "POST", path: "/api/v1/trips/10/stops", status: 201, body: makeStop() },
  ]);
  await user.click(await screen.findByRole("button", { name: "Add stop" }));
  const form = screen.getByRole("form", { name: "New stop" });
  await user.click(within(form).getByRole("button", { name: "Add stop" }));
  expect(within(form).getByText("Set where the stop is.")).toBeInTheDocument();

  await user.type(within(form).getByLabelText("Place name"), "Synthetic Lake");
  await user.type(within(form).getByLabelText(/Coordinates for/), "38.1, -97.1");
  await user.click(within(form).getByRole("button", { name: "Use" }));
  expect(within(form).getByTestId("place-point")).toHaveTextContent("38.10000, -97.10000");
  // A map click replaces it.
  await user.click(within(form).getByRole("button", { name: "Pick on map" }));
  expect(screen.getByText(/Click the map to place the new stop/)).toBeInTheDocument();
  useMapStore.getState().completePick({ lon: -96.5, lat: 38.5 });
  await waitFor(() =>
    expect(within(form).getByTestId("place-point")).toHaveTextContent("38.50000, -96.50000"),
  );
  await user.selectOptions(within(form).getByLabelText("Kind"), "Lodging");
  await user.click(within(form).getByRole("button", { name: "Add stop" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/stops")).toEqual({
      kind: "lodging",
      arrive_utc: null,
      depart_utc: null,
      tz: expect.any(String),
      place: { name: "Synthetic Lake", lon: -96.5, lat: 38.5 },
    }),
  );
});

test("a new leg starts where the last one ended and connects stops", async () => {
  const user = userEvent.setup();
  const motel = makeStop({
    id: 101,
    place: { ...makeStop().place, id: 501, name: "Synthetic Motel" },
  });
  const trip = makeDetail({
    stops: [makeStop(), motel],
    legs: [makeLeg({ origin_stop_id: 100, destination_stop_id: 101, end_tz: "America/Denver" })],
  });
  const { fetchMock } = renderAt("/trips/10/edit", [
    ...COMMON,
    { path: "/api/v1/trips/10", body: trip },
    { method: "POST", path: "/api/v1/trips/10/legs", status: 201, body: makeLeg({ id: 201 }) },
  ]);
  await user.click(await screen.findByRole("button", { name: "Add leg" }));
  const form = screen.getByRole("form", { name: "New leg" });
  expect(within(form).getByLabelText("From stop")).toHaveValue("101");
  await user.selectOptions(within(form).getByLabelText("To stop"), "Synthetic Lake");
  await user.type(within(form).getByLabelText("Departed"), "2024-05-02T08:15");
  await user.click(within(form).getByRole("button", { name: "Add leg" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/legs")).toMatchObject({
      mode: "drive",
      origin_stop_id: 101,
      destination_stop_id: 100,
      // Denver (the previous leg's arrival zone) is UTC-6 in May.
      start_utc: "2024-05-02T14:15:00Z",
      start_tz: "America/Denver",
      end_utc: null,
      origin_airport_id: null,
    }),
  );
});

test("moving a leg saves the whole new order", async () => {
  const user = userEvent.setup();
  const trip = makeDetail({
    legs: [
      makeLeg({ id: 200, origin_label: "A" }),
      makeLeg({ id: 201, sequence: 2, origin_label: "B" }),
    ],
  });
  const { fetchMock } = renderAt("/trips/10/edit", [
    ...COMMON,
    { path: "/api/v1/trips/10", body: trip },
    { method: "POST", path: "/api/v1/trips/10/legs/order", body: [] },
  ]);
  await user.click(await screen.findByRole("button", { name: /Move Drive B to \? up/ }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/legs/order")).toEqual({
      leg_ids: [201, 200],
    }),
  );
  expect(screen.getByRole("button", { name: /Move Drive A to \? up/ })).toBeDisabled();
});

test("Add me first creates my traveller profile when my account has none", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt(
    "/trips/10/edit",
    [
      ...COMMON,
      { path: "/api/v1/trips/10", body: makeDetail() },
      { method: "POST", path: "/api/v1/me/person", status: 201, body: { ...ME, person_id: 77 } },
      {
        method: "POST",
        path: "/api/v1/trips/10/participants",
        status: 201,
        body: makeParticipant(77, "Synthetic Member", { is_me: true }),
      },
    ],
    { ...ME, person_id: null },
  );
  await user.click(await screen.findByRole("button", { name: "Add me" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/participants")).toEqual({ person_id: 77 }),
  );
  const calls = requests(fetchMock);
  expect(calls.indexOf("POST /api/v1/me/person")).toBeLessThan(
    calls.indexOf("POST /api/v1/trips/10/participants"),
  );
});

test("people are added from the picker or created on the spot; removing asks the API", async () => {
  const user = userEvent.setup();
  const trip = makeDetail({ participants: [makeParticipant(8, "Synthetic Kid")] });
  const { fetchMock } = renderAt(
    "/trips/10/edit",
    [
      ...COMMON,
      { path: "/api/v1/trips/10", body: trip },
      {
        method: "POST",
        path: "/api/v1/trips/10/participants",
        status: 201,
        body: makeParticipant(7, "x"),
      },
      {
        method: "POST",
        path: "/api/v1/persons",
        status: 201,
        body: {
          id: 9,
          display_name: "Synthetic Friend",
          visibility: "family",
          is_me: false,
          has_account: false,
          can_edit: true,
        },
      },
      { method: "DELETE", path: "/api/v1/trips/10/participants/8", status: 204 },
    ],
    { ...ME, person_id: 3 },
  );
  await screen.findByRole("option", { name: "Synthetic Parent" });
  await user.selectOptions(screen.getByLabelText("Person to add"), "Synthetic Parent");
  await user.click(screen.getByRole("button", { name: /^Add$/ }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/participants")).toEqual({ person_id: 7 }),
  );
  await user.type(screen.getByLabelText("New person's name"), "Synthetic Friend");
  await user.click(screen.getByRole("button", { name: "Add new person" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/participants")).toEqual({ person_id: 9 }),
  );
  expect(lastBody(fetchMock, "POST", "/api/v1/persons")).toEqual({
    display_name: "Synthetic Friend",
  });
  await user.click(screen.getByRole("button", { name: "Remove Synthetic Kid" }));
  await waitFor(() =>
    expect(requests(fetchMock)).toContain("DELETE /api/v1/trips/10/participants/8"),
  );
});

test("a trip the caller can see but not edit says so", async () => {
  renderAt("/trips/10/edit", [
    ...COMMON,
    {
      path: "/api/v1/trips/10",
      body: makeDetail({
        access: { edit: false, delete: false, contribute: true, add_leg: "contribution" },
      }),
    },
  ]);
  expect(await screen.findByText("You can't edit this trip.")).toBeInTheDocument();
  expect(screen.queryByRole("form")).not.toBeInTheDocument();
});

test("a refused change shows the server's reason", async () => {
  const user = userEvent.setup();
  renderAt("/trips/10/edit", [
    ...COMMON,
    { path: "/api/v1/trips/10", body: makeDetail({ legs: [makeLeg()] }) },
    { method: "DELETE", path: "/api/v1/legs/200", status: 403, body: { detail: "not allowed" } },
  ]);
  await user.click(await screen.findByRole("button", { name: /Delete Drive/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("not allowed");
});
