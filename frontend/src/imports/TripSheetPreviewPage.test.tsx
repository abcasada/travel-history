import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import {
  getGetTripMapQueryKey,
  getGetTripQueryKey,
  getGetTripSheetPreviewQueryKey,
  getListTripsQueryKey,
} from "../api/generated";
import { saveFile } from "../platform/files";
import { lastBody, renderAt, requests } from "../test/render";
import { emptyDiff, makeBatch, makeIssue, makePreview, makeTab } from "../test/sheets";

vi.mock("../platform/files", () => ({ saveFile: vi.fn(), pickFiles: vi.fn() }));

const BATCH = { path: "/api/v1/imports/5", body: makeBatch() };
const PREVIEW_PATH = "/api/v1/imports/5/trip-sheet";
const COMMIT_PATH = "/api/v1/imports/5/commit";

const update = makeTab({
  record_id: 1,
  tab: "Lake trip",
  title: "Synthetic lake trip",
  outcome: "update",
  trip_id: 30,
  trip_updated_at: "2026-11-01T08:00:00.123Z",
  last_imported_at: "2026-10-01T08:00:00Z",
  diff: emptyDiff({
    trip: [{ field: "title", old: "Lake trip", new: "Synthetic lake trip" }],
    stops: {
      added: [{ row: 14, name: "Synthetic Cabin", changes: [] }],
      changed: [
        {
          row: 12,
          name: "Synthetic Start",
          stop_id: 80,
          changes: [{ field: "arrive_utc", old: null, new: "2024-05-01T14:00:00Z" }],
        },
      ],
      kept: [{ name: "Synthetic Old Stop", stop_id: 81, changes: [] }],
    },
  }),
});
const people = makeTab({
  record_id: 2,
  tab: "Beach trip",
  title: "Synthetic beach trip",
  outcome: "blocked",
  can_commit: false,
  unknown_people: ["Synthetic Cousin"],
  issues: [
    makeIssue({
      tab: "Beach trip",
      row: 6,
      column: "B",
      header: "",
      field: "people",
      reason: "unknown_person",
      message: "nobody called 'Synthetic Cousin' in the app",
      hint: "add the person in the app, or tick 'create these people' in the preview",
      candidates: ["Synthetic Cousin"],
    }),
  ],
});
const deleted = makeTab({
  record_id: 3,
  tab: "Old trip",
  title: "Synthetic old trip",
  outcome: "deleted",
});
const broken = makeTab({
  record_id: 4,
  tab: "Broken trip",
  title: "Synthetic broken trip",
  outcome: "blocked",
  can_commit: false,
  issues: [makeIssue({ tab: "Broken trip" })],
});
const PREVIEW = makePreview({ tabs: [update, people, deleted, broken] });

test("waits while the worker reads the sheet", async () => {
  renderAt("/imports/5", [
    { path: "/api/v1/imports/5", body: makeBatch({ status: "processing" }) },
  ]);
  expect(await screen.findByText(/Reading synthetic-trips.xlsx/)).toBeInTheDocument();
});

test("a failed or duplicate upload says so", async () => {
  renderAt("/imports/5", [
    {
      path: "/api/v1/imports/5",
      body: makeBatch({ status: "failed", error: "the file is larger than 10 MB" }),
    },
  ]);
  expect(await screen.findByText(/larger than 10 MB/)).toBeInTheDocument();
});

test("a duplicate links to the open preview of the same file", async () => {
  renderAt("/imports/6", [
    {
      path: "/api/v1/imports/6",
      body: makeBatch({ id: 6, status: "duplicate", summary: { duplicate_of_batch: 5 } }),
    },
  ]);
  const link = await screen.findByRole("link", { name: "Open that preview" });
  expect(link).toHaveAttribute("href", "/imports/5");
});

test("an unknown batch is not found", async () => {
  renderAt("/imports/99", []);
  expect(
    await screen.findByText("This import doesn't exist or isn't shared with you."),
  ).toBeInTheDocument();
});

test("shows each tab's outcome, issues with hints and candidates, the diff and the map", async () => {
  renderAt("/imports/5", [BATCH, { path: PREVIEW_PATH, body: PREVIEW }]);
  const lake = await screen.findByRole("region", { name: "Tab Lake trip" });
  expect(within(lake).getByText("Update")).toBeInTheDocument();
  expect(within(lake).getByText(/Title: Lake trip → Synthetic lake trip/)).toBeInTheDocument();
  expect(within(lake).getByText(/Arrive: – → 2024-05-01 14:00 UTC/)).toBeInTheDocument();
  expect(within(lake).getByText("Synthetic Cabin")).toBeInTheDocument();
  expect(within(lake).getByText(/Stops not in the sheet/)).toBeInTheDocument();
  expect(within(lake).getByRole("link", { name: "Open the trip" })).toHaveAttribute(
    "href",
    "/trips/30",
  );

  const brokenCard = screen.getByRole("region", { name: "Tab Broken trip" });
  expect(within(brokenCard).getByText("Blocked by problems")).toBeInTheDocument();
  const row = within(within(brokenCard).getByRole("table")).getAllByRole("row")[1] as HTMLElement;
  expect(within(row).getByText("12")).toBeInTheDocument();
  expect(within(row).getByText("B (Place)")).toBeInTheDocument();
  expect(within(row).getByText("add the region or country")).toBeInTheDocument();
  expect(within(row).getByText("Springfield, MO, US")).toBeInTheDocument();
  // A blocked tab can't be ticked for import.
  expect(within(brokenCard).queryByLabelText("Import this tab")).toBeNull();

  expect(screen.getByRole("button", { name: "Import 2 trips" })).toBeEnabled();
  // Every tab's stops and drivable legs are on the map.
  expect(screen.getByTestId("source-sheet-stops")).toHaveAttribute("data-features", "8");
  expect(screen.getByTestId("source-sheet-legs")).toHaveAttribute("data-features", "4");
});

test("the options start unticked; ticking them goes into the commit body", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/imports/5", [
    BATCH,
    { path: PREVIEW_PATH, body: PREVIEW },
    {
      method: "POST",
      path: COMMIT_PATH,
      body: {
        batch_id: 5,
        status: "done",
        results: [
          { record_id: 1, tab: "Lake trip", outcome: "updated", trip_id: 30, message: "" },
          { record_id: 2, tab: "Beach trip", outcome: "created", trip_id: 31, message: "" },
          { record_id: 3, tab: "Old trip", outcome: "created", trip_id: 32, message: "" },
        ],
      },
    },
  ]);
  const beach = await screen.findByRole("region", { name: "Tab Beach trip" });
  const create = within(beach).getByLabelText(/Create these people: Synthetic Cousin/);
  const recreate = screen.getByLabelText(/Re-create this trip/);
  const remove = screen.getByLabelText(/Also remove the stop or leg the sheet no longer has/);
  for (const box of [create, recreate, remove]) expect(box).not.toBeChecked();

  await user.click(create);
  // The tab blocked only by unknown people can now be imported.
  expect(within(beach).getByLabelText("Import this tab")).toBeChecked();
  await user.click(recreate);
  await user.click(remove);
  await user.click(screen.getByRole("button", { name: "Import 3 trips" }));

  expect(await screen.findByRole("region", { name: "Import results" })).toBeInTheDocument();
  expect(lastBody(fetchMock, "POST", COMMIT_PATH)).toEqual({
    records: [1, 2, 3],
    seen: [
      { record_id: 1, trip_updated_at: "2026-11-01T08:00:00.123Z" },
      { record_id: 2, trip_updated_at: null },
      { record_id: 3, trip_updated_at: null },
    ],
    create_people: [2],
    recreate: [3],
    remove_missing: [1],
  });
});

test("unticking a tab leaves it out", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/imports/5", [
    BATCH,
    { path: PREVIEW_PATH, body: PREVIEW },
    { method: "POST", path: COMMIT_PATH, body: { batch_id: 5, status: "done", results: [] } },
  ]);
  const lake = await screen.findByRole("region", { name: "Tab Lake trip" });
  await user.click(within(lake).getByLabelText("Import this tab"));
  await user.click(screen.getByRole("button", { name: "Import 1 trip" }));
  await waitFor(() => expect(lastBody(fetchMock, "POST", COMMIT_PATH)?.records).toEqual([3]));
});

test("after the commit the trips lists, the trip map and each written trip are refreshed", async () => {
  const user = userEvent.setup();
  const { client } = renderAt("/imports/5", [
    BATCH,
    { path: PREVIEW_PATH, body: makePreview({ tabs: [update] }) },
    {
      method: "POST",
      path: COMMIT_PATH,
      body: {
        batch_id: 5,
        status: "done",
        results: [{ record_id: 1, tab: "Lake trip", outcome: "updated", trip_id: 30, message: "" }],
      },
    },
  ]);
  const spy = vi.spyOn(client, "invalidateQueries");
  await user.click(await screen.findByRole("button", { name: "Import 1 trip" }));
  await screen.findByRole("region", { name: "Import results" });
  const keys = spy.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  expect(keys).toContain(JSON.stringify([...getListTripsQueryKey()]));
  expect(keys).toContain(JSON.stringify([...getGetTripMapQueryKey()]));
  expect(keys).toContain(JSON.stringify([...getGetTripQueryKey(30)]));
  expect(keys).toContain(JSON.stringify([...getGetTripSheetPreviewQueryKey(5)]));
});

test("409: the trip changed since the preview, so it is loaded again", async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAt("/imports/5", [
    BATCH,
    { path: PREVIEW_PATH, body: makePreview({ tabs: [update] }) },
    {
      method: "POST",
      path: COMMIT_PATH,
      status: 409,
      body: { detail: "a trip changed since the preview; preview again", records: [1] },
    },
  ]);
  await user.click(await screen.findByRole("button", { name: "Import 1 trip" }));
  expect(await screen.findByText(/Changed in the app since this preview: Lake trip/)).toBeVisible();
  await waitFor(() =>
    expect(requests(fetchMock).filter((r) => r === `GET ${PREVIEW_PATH}`)).toHaveLength(2),
  );
});

test("422: a tab that can't be imported is named", async () => {
  const user = userEvent.setup();
  renderAt("/imports/5", [
    BATCH,
    { path: PREVIEW_PATH, body: makePreview({ tabs: [update] }) },
    {
      method: "POST",
      path: COMMIT_PATH,
      status: 422,
      body: { detail: "tab 'Lake trip' has problems", records: [1] },
    },
  ]);
  await user.click(await screen.findByRole("button", { name: "Import 1 trip" }));
  expect(await screen.findByText(/Can't be imported as it is now: Lake trip/)).toBeVisible();
});

test("the problem report is saved as CSV through the files adapter", async () => {
  const user = userEvent.setup();
  renderAt("/imports/5", [BATCH, { path: PREVIEW_PATH, body: PREVIEW }]);
  await user.click(await screen.findByRole("button", { name: "Download report (CSV)" }));
  expect(saveFile).toHaveBeenCalledWith(
    "synthetic-trips-report.csv",
    expect.stringMatching(/^tab,row,column,severity,reason,message,hint\r\nBeach trip,6,B,/),
    "text/csv",
  );
});

test("show on map highlights that tab in the URL", async () => {
  const user = userEvent.setup();
  renderAt("/imports/5", [BATCH, { path: PREVIEW_PATH, body: PREVIEW }]);
  const beach = await screen.findByRole("region", { name: "Tab Beach trip" });
  await user.click(within(beach).getByRole("button", { name: "Show on map" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/imports/5?tab=2");
});

test("a committed batch shows what happened and offers no import", async () => {
  renderAt("/imports/5", [
    { path: "/api/v1/imports/5", body: makeBatch({ status: "done" }) },
    {
      path: PREVIEW_PATH,
      body: makePreview({
        status: "done",
        can_commit: false,
        tabs: [makeTab({ outcome: "new", committed: "created", can_commit: false, trip_id: 31 })],
      }),
    },
  ]);
  expect(await screen.findByText("Imported: new trip")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Import/ })).toBeNull();
  expect(screen.queryByLabelText("Import this tab")).toBeNull();
});

test("discard asks first and ends the batch", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { fetchMock } = renderAt("/imports/5", [
    BATCH,
    { path: PREVIEW_PATH, body: PREVIEW },
    { method: "POST", path: "/api/v1/imports/5/discard", status: 204 },
  ]);
  await user.click(await screen.findByRole("button", { name: "Discard" }));
  await waitFor(() => expect(requests(fetchMock)).toContain("POST /api/v1/imports/5/discard"));
});
