/** The complete trip page (item 21b): tags, notes, consent, own legs and per-leg presence. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MeOut } from "../api/generated";
import { ME } from "../test/fetch";
import { lastBody, renderAt, requests } from "../test/render";
import { EMPTY_MAP, makeDetail, makeLeg, makeParticipant } from "../test/trips";

const MAP = { path: "/api/v1/trips/map", body: EMPTY_MAP };
const OTHER = { id: 2, display_name: "Synthetic Owner" };
// The caller (person 7) is a participant on someone else's trip.
const PARTICIPANT = { ...ME, person_id: 7 } as MeOut;

const NOTE = {
  id: 50,
  trip_id: 10,
  author: OTHER,
  public_consent: false,
  created_at: "2024-05-04T10:00:00Z",
  updated_at: "2024-05-04T10:00:00Z",
  body: "Synthetic: the owner's note",
  can_edit: false,
  can_delete: false,
};
const MY_NOTE = {
  ...NOTE,
  id: 51,
  author: { id: 1, display_name: "Synthetic Member" },
  body: "Synthetic: my note",
  can_edit: true,
  can_delete: true,
};

const CORE_LEG = makeLeg({
  author: OTHER,
  can_edit: false,
  can_delete: false,
  origin_label: "Synthetic Home",
  destination_label: "Synthetic Lake",
  participant_ids: [7, 8],
});
const MY_LEG = makeLeg({
  id: 201,
  sequence: 2,
  is_contribution: true,
  participant_scope: "author",
  origin_label: "Synthetic Lake",
  destination_label: "Synthetic Cabin",
  notes: "Synthetic: took the ferry",
  participant_ids: [7],
});

const TRIP = makeDetail({
  is_owner: false,
  owner: OTHER,
  access: { edit: false, delete: false, contribute: true, add_leg: "contribution" },
  participants: [
    makeParticipant(7, "Synthetic Member", { is_me: true, can_set_consent: true }),
    makeParticipant(8, "Synthetic Kid"),
  ],
  legs: [CORE_LEG, MY_LEG],
  tags: [
    { id: 3, name: "lakes", color: "", author: OTHER, by_owner: true },
    { id: 4, name: "mine", color: "", author: { id: 1, display_name: "Me" }, by_owner: false },
  ],
});

const TRIP_TAGS = [
  { ...TRIP.tags[0], can_remove: false },
  { ...TRIP.tags[1], can_remove: true },
];

function page(extra: { method?: string; path: string; status?: number; body?: unknown }[] = []) {
  return renderAt(
    "/trips/10",
    [
      MAP,
      { path: "/api/v1/trips/10", body: TRIP },
      { path: "/api/v1/trips/10/tags", body: TRIP_TAGS },
      { path: "/api/v1/trips/10/notes", body: [NOTE, MY_NOTE] },
      {
        path: "/api/v1/tags",
        body: [
          { id: 4, name: "mine", color: "", trip_count: 1 },
          { id: 5, name: "summer", color: "", trip_count: 0 },
        ],
      },
      ...extra,
    ],
    PARTICIPANT,
  );
}

test("tags show who added them; only removable ones get a remove button", async () => {
  const user = userEvent.setup();
  const { fetchMock } = page([
    { method: "DELETE", path: "/api/v1/trips/10/tags/4", status: 204 },
  ]);
  const tags = await screen.findByRole("region", { name: "Tags" });
  expect(tags).toHaveTextContent("#lakes");
  expect(tags).toHaveTextContent("#mine(Me)");
  await user.click(await within(tags).findByRole("button", { name: "Remove tag mine" }));
  expect(within(tags).queryByRole("button", { name: "Remove tag lakes" })).toBeNull();
  await waitFor(() => expect(requests(fetchMock)).toContain("DELETE /api/v1/trips/10/tags/4"));
});

test("tagging uses an own tag by id, or creates one by name", async () => {
  const user = userEvent.setup();
  const { fetchMock } = page([
    { method: "POST", path: "/api/v1/trips/10/tags", status: 201, body: TRIP_TAGS },
  ]);
  const box = await screen.findByLabelText("Tag name");
  // Wait for the caller's own tags (the suggestions) before typing a known name.
  await waitFor(() => expect(requests(fetchMock)).toContain("GET /api/v1/tags"));
  await user.type(box, "Summer");
  await user.click(screen.getByRole("button", { name: "Tag" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/tags")).toEqual({ tag_id: 5 }),
  );
  await waitFor(() => expect(box).toHaveValue(""));
  await user.type(box, "#new one");
  await user.click(screen.getByRole("button", { name: "Tag" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/tags")).toEqual({ name: "new one" }),
  );
});

test("notes: everyone reads them; the author edits and deletes their own", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { fetchMock } = page([
    { method: "POST", path: "/api/v1/trips/10/notes", status: 201, body: MY_NOTE },
    { method: "PATCH", path: "/api/v1/notes/51", body: MY_NOTE },
    { method: "DELETE", path: "/api/v1/notes/51", status: 204 },
  ]);
  const notes = await screen.findByRole("region", { name: "Notes" });
  expect(await within(notes).findByText("Synthetic: the owner's note")).toBeInTheDocument();
  expect(within(notes).getAllByRole("button", { name: /^Edit note/ })).toHaveLength(1);
  expect(within(notes).getAllByRole("button", { name: /^Delete note/ })).toHaveLength(1);

  await user.click(within(notes).getByRole("button", { name: "Add note" }));
  const form = within(notes).getByRole("form", { name: "New note" });
  await user.click(within(form).getByRole("button", { name: "Add note" }));
  expect(within(form).getByText("Write something first.")).toBeInTheDocument();
  await user.type(within(form).getByLabelText("Note"), "Synthetic: a new note");
  await user.click(within(form).getByRole("button", { name: "Add note" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/notes")).toEqual({
      body: "Synthetic: a new note",
    }),
  );

  await user.click(
    await within(notes).findByRole("button", { name: "Edit note by Synthetic Member" }),
  );
  const edit = within(notes).getByRole("form", { name: "Edit note" });
  await user.clear(within(edit).getByLabelText("Note"));
  await user.type(within(edit).getByLabelText("Note"), "Synthetic: changed");
  await user.click(within(edit).getByRole("button", { name: "Save note" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/notes/51")).toEqual({
      body: "Synthetic: changed",
    }),
  );
  await user.click(
    await within(notes).findByRole("button", { name: "Delete note by Synthetic Member" }),
  );
  await waitFor(() => expect(requests(fetchMock)).toContain("DELETE /api/v1/notes/51"));
});

test("a participant edits the notes of their own leg, not the owner's legs", async () => {
  const user = userEvent.setup();
  const { fetchMock } = page([{ method: "PATCH", path: "/api/v1/legs/201", body: MY_LEG }]);
  const legs = await screen.findByRole("region", { name: "Itinerary" });
  expect(legs).toHaveTextContent("added by Synthetic Member");
  expect(
    within(legs).queryByRole("button", { name: "Edit Drive Synthetic Home to Synthetic Lake" }),
  ).toBeNull();
  await user.click(
    within(legs).getByRole("button", { name: "Edit Drive Synthetic Lake to Synthetic Cabin" }),
  );
  const form = within(legs).getByRole("form", { name: "Edit leg" });
  const notes = within(form).getByLabelText("Leg notes");
  expect(notes).toHaveValue("Synthetic: took the ferry");
  await user.clear(notes);
  await user.type(notes, "Synthetic: took the late ferry");
  await user.click(within(form).getByRole("button", { name: "Save leg" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/legs/201")).toMatchObject({
      mode: "drive",
      notes: "Synthetic: took the late ferry",
    }),
  );
  // A contributed leg never sends a participant scope (the API fixes it to the author).
  expect(lastBody(fetchMock, "PATCH", "/api/v1/legs/201")).not.toHaveProperty(
    "participant_scope",
  );
});

test("a participant adds their own leg", async () => {
  const user = userEvent.setup();
  const { fetchMock } = page([
    { method: "POST", path: "/api/v1/trips/10/legs", status: 201, body: MY_LEG },
  ]);
  await user.click(await screen.findByRole("button", { name: "Add my leg" }));
  const form = screen.getByRole("form", { name: "New leg" });
  await user.selectOptions(within(form).getByLabelText("Mode"), "walk");
  await user.type(within(form).getByLabelText("From (label)"), "Synthetic Cabin");
  await user.type(within(form).getByLabelText("Leg notes"), "Synthetic: a walk");
  await user.click(within(form).getByRole("button", { name: "Add leg" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/trips/10/legs")).toMatchObject({
      mode: "walk",
      origin_label: "Synthetic Cabin",
      notes: "Synthetic: a walk",
    }),
  );
});

test("participants say which legs they were on and set their own public consent", async () => {
  const user = userEvent.setup();
  const { fetchMock } = page([
    { method: "PUT", path: "/api/v1/legs/200/my-participation", body: CORE_LEG },
    { method: "PUT", path: "/api/v1/trips/10/participants/7/consent", body: TRIP.participants[0] },
  ]);
  const onLeg = await screen.findByLabelText("I was on Drive Synthetic Home to Synthetic Lake");
  expect(onLeg).toBeChecked();
  await user.click(onLeg);
  await waitFor(() =>
    expect(lastBody(fetchMock, "PUT", "/api/v1/legs/200/my-participation")).toEqual({
      on_leg: false,
    }),
  );
  // Only the caller's own row has the switch.
  expect(screen.queryByLabelText("Synthetic Kid may appear on public pages")).toBeNull();
  await user.click(screen.getByLabelText("Synthetic Member may appear on public pages"));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PUT", "/api/v1/trips/10/participants/7/consent")).toEqual({
      public_consent: true,
    }),
  );
});

test("someone who can't contribute gets no tag box, note button, own legs or leg switches", async () => {
  const readOnly = makeDetail({
    is_owner: false,
    access: { edit: false, delete: false, contribute: false, add_leg: null },
    legs: [CORE_LEG],
  });
  renderAt(
    "/trips/10",
    [
      MAP,
      { path: "/api/v1/trips/10", body: readOnly },
      { path: "/api/v1/trips/10/tags", body: [] },
      { path: "/api/v1/trips/10/notes", body: [NOTE] },
    ],
    PARTICIPANT,
  );
  expect(await screen.findByText("Synthetic: the owner's note")).toBeInTheDocument();
  expect(screen.queryByLabelText("Tag name")).toBeNull();
  expect(screen.queryByRole("button", { name: "Add note" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Add my leg" })).toBeNull();
  expect(screen.queryByLabelText(/^I was on/)).toBeNull();
});

test("flight legs show airport codes, airline, seat and cabin", async () => {
  const flight = makeLeg({
    mode: "flight",
    flight_number: "123",
    airline: { id: 9, name: "Synthetic Air", code: "SY" },
    origin_airport: { id: 1, name: "Synthetic Intl", code: "SYA" },
    destination_airport: { id: 2, name: "Synthetic Field", code: "SYB" },
    seat: "12A",
    cabin_class: "premium_economy",
  });
  renderAt("/trips/10", [
    MAP,
    { path: "/api/v1/trips/10", body: makeDetail({ legs: [flight] }) },
    { path: "/api/v1/trips/10/tags", body: [] },
    { path: "/api/v1/trips/10/notes", body: [] },
  ]);
  const legs = await screen.findByRole("region", { name: "Itinerary" });
  expect(legs).toHaveTextContent("Flight SYA → SYB");
  expect(legs).toHaveTextContent("SYA → SYB · SY 123 · seat 12A · Premium economy");
});
