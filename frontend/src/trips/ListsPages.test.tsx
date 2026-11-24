/** The small list pages behind the trip pages (item 21b): /tags, /purposes, /people. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MeOut } from "../api/generated";
import { ME } from "../test/fetch";
import { lastBody, renderAt, requests } from "../test/render";
import { EMPTY_MAP } from "../test/trips";

const MAP = { path: "/api/v1/trips/map", body: EMPTY_MAP };
const VIEWER = { ...ME, role: "viewer" } as MeOut;

// --- /tags -------------------------------------------------------------------------------------

const TAGS = [
  { id: 5, name: "lakes", color: "#2563eb", trip_count: 3 },
  { id: 6, name: "summer", color: "", trip_count: 1 },
];

test("my tags: rename and colour one, checking the colour first", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/tags", [
    MAP,
    { path: "/api/v1/tags", body: TAGS },
    { method: "PATCH", path: "/api/v1/tags/5", body: TAGS[0] },
  ]);
  expect(await screen.findByText("#lakes")).toBeInTheDocument();
  expect(screen.getByText("3 trips")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Edit #lakes" }));
  const form = screen.getByRole("form", { name: "Edit tag lakes" });
  await user.clear(within(form).getByLabelText("Tag name"));
  await user.type(within(form).getByLabelText("Tag name"), "big lakes");
  await user.clear(within(form).getByLabelText("Colour"));
  await user.type(within(form).getByLabelText("Colour"), "blue");
  await user.click(within(form).getByRole("button", { name: "Save" }));
  expect(within(form).getByText("Use a colour like #2563eb.")).toBeInTheDocument();
  expect(requests(fetchMock).some((r) => r.startsWith("PATCH"))).toBe(false);
  await user.clear(within(form).getByLabelText("Colour"));
  await user.type(within(form).getByLabelText("Colour"), "#16a34a");
  await user.click(within(form).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/tags/5")).toEqual({
      name: "big lakes",
      color: "#16a34a",
    }),
  );
});

test("my tags: deleting asks first and says how many trips lose it", async () => {
  const user = userEvent.setup();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const { fetchMock } = renderAt("/tags", [
    MAP,
    { path: "/api/v1/tags", body: TAGS },
    { method: "DELETE", path: "/api/v1/tags/6", status: 204 },
  ]);
  await user.click(await screen.findByRole("button", { name: "Delete #summer" }));
  expect(confirm).toHaveBeenCalledWith("Delete #summer? It comes off 1 trip.");
  await waitFor(() => expect(requests(fetchMock)).toContain("DELETE /api/v1/tags/6"));
});

test("my tags: an empty list says where tags come from", async () => {
  renderAt("/tags", [MAP, { path: "/api/v1/tags", body: [] }]);
  expect(await screen.findByText("No tags yet. Add one from a trip's page.")).toBeInTheDocument();
});

// --- /purposes ---------------------------------------------------------------------------------

const PURPOSES = [
  { id: 1, name: "Work", default_visibility: "private", sort: 0, archived: false },
  { id: 2, name: "Vacation", default_visibility: "participants", sort: 1, archived: false },
  { id: 3, name: "Moving", default_visibility: "participants", sort: 2, archived: true },
];

test("my purposes: add one; public is never offered as a default", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/purposes", [
    MAP,
    { path: "/api/v1/purposes", body: PURPOSES },
    { method: "POST", path: "/api/v1/purposes", status: 201, body: PURPOSES[0] },
  ]);
  const form = await screen.findByRole("form", { name: "New purpose" });
  await user.click(within(form).getByRole("button", { name: "Add purpose" }));
  expect(within(form).getByText("A purpose needs a name.")).toBeInTheDocument();
  await user.type(within(form).getByLabelText("New purpose"), " Conference ");
  const visibility = within(form).getByLabelText("Default visibility");
  expect(within(visibility).queryByRole("option", { name: "Public" })).toBeNull();
  await user.selectOptions(visibility, "family");
  await user.click(within(form).getByRole("button", { name: "Add purpose" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "POST", "/api/v1/purposes")).toEqual({
      name: "Conference",
      default_visibility: "family",
    }),
  );
});

test("my purposes: rename, archive and reorder", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/purposes", [
    MAP,
    { path: "/api/v1/purposes", body: PURPOSES },
    { method: "PATCH", path: "/api/v1/purposes/1", body: PURPOSES[0] },
    { method: "PATCH", path: "/api/v1/purposes/2", body: PURPOSES[1] },
    { method: "PATCH", path: "/api/v1/purposes/3", body: PURPOSES[2] },
  ]);
  expect(await screen.findByText("Moving (archived)")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Rename Work" }));
  const rename = screen.getByRole("form", { name: "Rename Work" });
  await user.clear(within(rename).getByLabelText("Purpose name"));
  await user.type(within(rename).getByLabelText("Purpose name"), "Business");
  await user.click(within(rename).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/purposes/1")).toEqual({ name: "Business" }),
  );
  await user.click(screen.getByRole("button", { name: "Restore Moving" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/purposes/3")).toEqual({ archived: false }),
  );
  // Moving Vacation up renumbers the two that change.
  await user.click(screen.getByRole("button", { name: "Move Vacation up" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/purposes/1")).toEqual({ sort: 1 }),
  );
  expect(lastBody(fetchMock, "PATCH", "/api/v1/purposes/2")).toEqual({ sort: 0 });
});

test("viewers have no purposes page", async () => {
  renderAt("/purposes", [MAP], VIEWER);
  expect(await screen.findByText("Viewers don't have trip purposes.")).toBeInTheDocument();
});

// --- /people -----------------------------------------------------------------------------------

const PEOPLE = [
  {
    id: 7,
    display_name: "Synthetic Member",
    visibility: "family",
    is_me: true,
    has_account: true,
    can_edit: true,
    manages: true,
  },
  {
    id: 8,
    display_name: "Synthetic Kid",
    visibility: "private",
    is_me: false,
    has_account: false,
    can_edit: true,
    manages: true,
  },
  {
    id: 9,
    display_name: "Synthetic Cousin",
    visibility: "family",
    is_me: false,
    has_account: true,
    can_edit: false,
    manages: false,
  },
];

test("people: rename and change who sees the people you manage", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/people", [
    MAP,
    { path: "/api/v1/persons", body: PEOPLE },
    { method: "PATCH", path: "/api/v1/persons/8", body: PEOPLE[1] },
  ]);
  expect(await screen.findByText("(me)")).toBeInTheDocument();
  // Someone else's account: listed, not editable.
  expect(screen.queryByRole("button", { name: "Rename Synthetic Cousin" })).toBeNull();
  expect(screen.getByText("Synthetic Cousin")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Rename Synthetic Kid" }));
  const form = screen.getByRole("form", { name: "Rename Synthetic Kid" });
  await user.clear(within(form).getByLabelText("Name"));
  await user.click(within(form).getByRole("button", { name: "Save" }));
  expect(within(form).getByText("A person needs a name.")).toBeInTheDocument();
  await user.type(within(form).getByLabelText("Name"), "Synthetic Child");
  await user.click(within(form).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/persons/8")).toEqual({
      display_name: "Synthetic Child",
    }),
  );
  await user.selectOptions(screen.getByLabelText("Who sees Synthetic Kid"), "family");
  await waitFor(() =>
    expect(lastBody(fetchMock, "PATCH", "/api/v1/persons/8")).toEqual({ visibility: "family" }),
  );
});

test("people: the server's refusal is shown", async () => {
  const user = userEvent.setup();
  renderAt("/people", [
    MAP,
    { path: "/api/v1/persons", body: PEOPLE },
    {
      method: "PATCH",
      path: "/api/v1/persons/8",
      status: 403,
      body: { detail: "only the person's managing user or the Admin can change them" },
    },
  ]);
  await user.selectOptions(await screen.findByLabelText("Who sees Synthetic Kid"), "family");
  expect(
    await screen.findByText(/only the person's managing user or the Admin can change them/),
  ).toBeInTheDocument();
});

test("people: a viewer may change nobody", async () => {
  renderAt("/people", [MAP, { path: "/api/v1/persons", body: [PEOPLE[2]] }], VIEWER);
  expect(await screen.findByText("There's nobody you can change.")).toBeInTheDocument();
  expect(screen.getByText("Synthetic Cousin")).toBeInTheDocument();
});
