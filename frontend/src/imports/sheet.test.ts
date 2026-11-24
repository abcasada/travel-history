import { emptyDiff, makeIssue, makePreview, makeTab } from "../test/sheets";
import {
  blockedOnlyByUnknownPeople,
  canRemoveMissing,
  columnLabel,
  commitBody,
  emptyChoices,
  importable,
  included,
  issueCounts,
  outcomeLabel,
  reportCsv,
  reportName,
  sheetBounds,
  sheetLegFeatures,
  sheetStopFeatures,
  toggled,
} from "./sheet";

const personIssue = makeIssue({
  row: 4,
  column: "B",
  header: "",
  field: "people",
  reason: "unknown_person",
  message: "nobody called 'Synthetic Cousin' in the app",
  hint: "tick 'create these people' in the preview",
  candidates: ["Synthetic Cousin"],
});
const blockedByPeople = makeTab({
  record_id: 2,
  outcome: "blocked",
  can_commit: false,
  issues: [personIssue],
  unknown_people: ["Synthetic Cousin"],
});

test("a tab blocked only by unknown people becomes importable once they are to be created", () => {
  expect(blockedOnlyByUnknownPeople(blockedByPeople)).toBe(true);
  expect(importable(blockedByPeople, emptyChoices())).toBe(false);
  const choices = { ...emptyChoices(), createPeople: new Set([2]) };
  expect(importable(blockedByPeople, choices)).toBe(true);
  expect(included(blockedByPeople, choices)).toBe(true);
  // Unticking the tab itself leaves it out again.
  expect(included(blockedByPeople, { ...choices, excluded: new Set([2]) })).toBe(false);
});

test("other problems keep a tab blocked whatever is ticked", () => {
  const tab = makeTab({
    ...blockedByPeople,
    issues: [personIssue, makeIssue()],
  });
  expect(blockedOnlyByUnknownPeople(tab)).toBe(false);
  expect(importable(tab, { ...emptyChoices(), createPeople: new Set([2]) })).toBe(false);
  // "me" without a linked person can't be created: no candidate.
  const me = makeTab({ ...blockedByPeople, issues: [{ ...personIssue, candidates: [] }] });
  expect(blockedOnlyByUnknownPeople(me)).toBe(false);
});

test("the commit body names the chosen tabs, what they looked like, and only their ticks", () => {
  const update = makeTab({
    record_id: 1,
    outcome: "update",
    trip_id: 30,
    trip_updated_at: "2026-11-01T08:00:00.123Z",
  });
  const deleted = makeTab({ record_id: 3, outcome: "deleted" });
  const skipped = makeTab({ record_id: 4, outcome: "identical", trip_id: 31 });
  const preview = makePreview({ tabs: [update, blockedByPeople, deleted, skipped] });
  const choices = {
    excluded: new Set([4]),
    createPeople: new Set([2]),
    recreate: new Set([3]),
    removeMissing: new Set([1, 4]),
  };
  expect(commitBody(preview, choices)).toEqual({
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
  // Nothing ticked: every importable tab, no options.
  expect(commitBody(preview, emptyChoices())).toMatchObject({
    records: [1, 3, 4],
    create_people: [],
    recreate: [],
    remove_missing: [],
  });
});

test("removing kept rows is offered only for updates that keep rows", () => {
  const kept = emptyDiff({
    stops: { added: [], changed: [], kept: [{ name: "Old stop", stop_id: 9, changes: [] }] },
  });
  expect(canRemoveMissing(makeTab({ outcome: "update", diff: kept }))).toBe(true);
  expect(canRemoveMissing(makeTab({ outcome: "review", diff: kept }))).toBe(false);
  expect(canRemoveMissing(makeTab({ outcome: "update", diff: emptyDiff() }))).toBe(false);
  expect(canRemoveMissing(makeTab({ outcome: "update", diff: kept, committed: "updated" }))).toBe(
    false,
  );
});

test("outcome labels prefer what the commit did", () => {
  expect(outcomeLabel(makeTab({ outcome: "review" }))).toBe("Review: edited in the app");
  expect(outcomeLabel(makeTab({ outcome: "new", committed: "created" }))).toBe(
    "Imported: new trip",
  );
});

test("toggled returns a new set", () => {
  const start = new Set([1]);
  expect([...toggled(start, 2, true)]).toEqual([1, 2]);
  expect([...toggled(start, 1, false)]).toEqual([]);
  expect([...start]).toEqual([1]);
});

test("the CSV report has the CLI's columns, workbook issues first, quoted where needed", () => {
  const preview = makePreview({
    workbook_issues: [
      makeIssue({
        tab: "",
        row: null,
        column: "",
        header: "",
        severity: "problem",
        reason: "duplicate_key",
        message: "two tabs use the key 'lake'",
        hint: "",
      }),
    ],
    tabs: [
      makeTab({
        issues: [
          makeIssue({
            row: 14,
            severity: "warning",
            reason: "bad_value",
            message: 'cabin "suite"',
          }),
          makeIssue({ row: 12, hint: "add the region, or country" }),
        ],
      }),
    ],
  });
  expect(reportCsv(preview).split("\r\n")).toEqual([
    "tab,row,column,severity,reason,message,hint",
    ",,,problem,duplicate_key,two tabs use the key 'lake',",
    `Lake trip,12,B (Place),problem,ambiguous_place,2 places are called 'Springfield',"add the region, or country"`,
    `Lake trip,14,B (Place),warning,bad_value,"cabin ""suite""",add the region or country`,
    "",
  ]);
  expect(issueCounts(preview)).toEqual({ problems: 2, warnings: 1, total: 3 });
});

test("column labels and report names", () => {
  expect(columnLabel({ column: "C", header: "Place" })).toBe("C (Place)");
  expect(columnLabel({ column: "", header: "Title" })).toBe("Title");
  expect(columnLabel({ column: "", header: "" })).toBe("");
  expect(reportName("Trips 2024.xlsx", 5)).toBe("Trips 2024-report.csv");
  expect(reportName(null, 5)).toBe("trip-sheet-5-report.csv");
});

test("map features: stops per tab, legs with both ends, flights as arcs", () => {
  const tab = makeTab({
    record_id: 7,
    legs: [
      { row: 17, name: "A → B", mode: "drive", origin: [-97, 37], destination: [-96, 38] },
      { row: 18, name: "B → ?", mode: "drive", origin: [-96, 38], destination: null },
      { row: 19, name: "B → C", mode: "flight", origin: [-96, 38], destination: [-80, 26] },
    ],
  });
  const stops = sheetStopFeatures([tab]);
  expect(stops.features).toHaveLength(2);
  expect(stops.features[0]?.properties).toEqual({ record_id: 7, row: 12, name: "Synthetic Start" });
  const legs = sheetLegFeatures([tab]);
  expect(legs.features.map((f) => f.properties.row)).toEqual([17, 19]);
  expect(legs.features[0]?.geometry.coordinates).toHaveLength(2);
  expect(legs.features[1]?.geometry.coordinates.length).toBeGreaterThan(2);
  const box = sheetBounds([tab])?.flat() ?? [];
  for (const [i, value] of [-97.3, 26, -80, 38.2].entries()) expect(box[i]).toBeCloseTo(value, 6);
  expect(sheetBounds([makeTab({ stops: [], legs: [] })])).toBeNull();
});
