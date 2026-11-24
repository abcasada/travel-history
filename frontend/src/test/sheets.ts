/** Synthetic trip spreadsheet previews for frontend tests (fake people and places only).
 * Override any field per test. */
import type {
  ImportBatchOut,
  SheetDiffOut,
  SheetIssueOut,
  SheetTabOut,
  TripSheetPreviewOut,
} from "../api/generated";

export function makeIssue(over: Partial<SheetIssueOut> = {}): SheetIssueOut {
  return {
    tab: "Lake trip",
    row: 12,
    column: "B",
    header: "Place",
    field: "place",
    severity: "problem",
    reason: "ambiguous_place",
    message: "2 places are called 'Springfield'",
    hint: "add the region or country",
    candidates: ["Springfield, IL, US", "Springfield, MO, US"],
    ...over,
  };
}

export function emptyDiff(over: Partial<SheetDiffOut> = {}): SheetDiffOut {
  return {
    trip: [],
    people_added: [],
    tags_added: [],
    stops: { added: [], changed: [], kept: [] },
    legs: { added: [], changed: [], kept: [] },
    ...over,
  };
}

export function makeTab(over: Partial<SheetTabOut> = {}): SheetTabOut {
  return {
    record_id: 1,
    tab: "Lake trip",
    position: 0,
    key: "lake-trip",
    title: "Synthetic lake trip",
    outcome: "new",
    committed: "",
    can_commit: true,
    issues: [],
    unknown_people: [],
    new_tags: [],
    trip_id: null,
    trip_updated_at: null,
    last_imported_at: null,
    diff: emptyDiff({
      stops: {
        added: [
          { row: 12, name: "Synthetic Start", changes: [] },
          { row: 13, name: "Synthetic Lake", changes: [] },
        ],
        changed: [],
        kept: [],
      },
      legs: {
        added: [{ row: 17, name: "Synthetic Start → Synthetic Lake", mode: "drive", changes: [] }],
        changed: [],
        kept: [],
      },
    }),
    stops: [
      { row: 12, name: "Synthetic Start", kind: "waypoint", lon: -97.3, lat: 37.7 },
      { row: 13, name: "Synthetic Lake", kind: "destination", lon: -96.5, lat: 38.2 },
    ],
    legs: [
      {
        row: 17,
        name: "Synthetic Start → Synthetic Lake",
        mode: "drive",
        origin: [-97.3, 37.7],
        destination: [-96.5, 38.2],
      },
    ],
    ...over,
  };
}

export function makePreview(over: Partial<TripSheetPreviewOut> = {}): TripSheetPreviewOut {
  return {
    batch_id: 5,
    status: "preview",
    original_name: "synthetic-trips.xlsx",
    can_commit: true,
    workbook_issues: [],
    tabs: [makeTab()],
    ...over,
  };
}

export function makeBatch(over: Partial<ImportBatchOut> = {}): ImportBatchOut {
  return {
    id: 5,
    kind: "trip_sheet",
    status: "preview",
    original_name: "synthetic-trips.xlsx",
    size_bytes: 12_000,
    summary: {},
    error: "",
    created_at: "2026-11-20T10:00:00Z",
    finished_at: "2026-11-20T10:00:05Z",
    ...over,
  };
}
