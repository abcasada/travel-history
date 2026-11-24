/**
 * The trip spreadsheet preview's logic, kept out of the components so it is unit-tested
 * (docs/design/trip-sheet.md §28.7-§28.9, D-101): outcome labels, which tabs can be imported
 * with the user's ticks, the commit body, the CSV problem report and the map's GeoJSON.
 */
import type { FeatureCollection, LineString, Point, Position } from "geojson";
import type {
  SheetIssueOut,
  SheetTabOut,
  TripSheetCommitIn,
  TripSheetPreviewOut,
} from "../api/generated";
import { greatCircle } from "../map/geo";

/** What committing a tab would do (`outcome` while the batch is open). */
export const OUTCOME_LABELS: Record<string, string> = {
  new: "New trip",
  update: "Update",
  identical: "No changes",
  review: "Review: edited in the app",
  deleted: "Skipped: deleted in the app",
  transferred: "Skipped: no longer your trip",
  blocked: "Blocked by problems",
  not_committed: "Not imported",
};

/** What the commit did (`committed`, stored on the record). */
export const COMMITTED_LABELS: Record<string, string> = {
  created: "Imported: new trip",
  updated: "Imported: trip updated",
  identical: "No changes",
  review: "Sent to review",
  skipped: "Skipped",
};

export const OUTCOME_TONES: Record<string, string> = {
  new: "bg-green-100 text-green-900",
  update: "bg-blue-100 text-blue-900",
  identical: "bg-slate-100 text-slate-700",
  review: "bg-amber-100 text-amber-900",
  deleted: "bg-slate-100 text-slate-700",
  transferred: "bg-slate-100 text-slate-700",
  blocked: "bg-red-100 text-red-900",
};

export function outcomeLabel(tab: SheetTabOut): string {
  if (tab.committed) return COMMITTED_LABELS[tab.committed] ?? tab.committed;
  return OUTCOME_LABELS[tab.outcome] ?? tab.outcome;
}

/** The user's choices per tab, as record-id sets (D-101). All start empty: every option is
 * off until ticked, and `excluded` holds importable tabs the user unticked. */
export type Choices = {
  excluded: Set<number>;
  createPeople: Set<number>;
  recreate: Set<number>;
  removeMissing: Set<number>;
};

export function emptyChoices(): Choices {
  return {
    excluded: new Set(),
    createPeople: new Set(),
    recreate: new Set(),
    removeMissing: new Set(),
  };
}

export function toggled(set: Set<number>, id: number, on: boolean): Set<number> {
  const next = new Set(set);
  if (on) next.add(id);
  else next.delete(id);
  return next;
}

const problems = (tab: SheetTabOut) => tab.issues.filter((i) => i.severity === "problem");

/** A blocked tab whose only problems are people the importer may create (Q-20): ticking
 * "create these people" makes it importable. Mirrors the server's `plan.problems`. */
export function blockedOnlyByUnknownPeople(tab: SheetTabOut): boolean {
  const found = problems(tab);
  return (
    tab.outcome === "blocked" &&
    !tab.committed &&
    found.length > 0 &&
    found.every((i) => i.reason === "unknown_person" && i.candidates.length > 0)
  );
}

/** Can this tab go into the commit, given the ticks? */
export function importable(tab: SheetTabOut, choices: Choices): boolean {
  if (tab.can_commit) return true;
  return blockedOnlyByUnknownPeople(tab) && choices.createPeople.has(tab.record_id);
}

/** Is it going in (importable and not unticked)? */
export function included(tab: SheetTabOut, choices: Choices): boolean {
  return importable(tab, choices) && !choices.excluded.has(tab.record_id);
}

/** Stops and legs the trip has but the sheet no longer lists (kept unless the user asks). */
export function keptRows(tab: SheetTabOut) {
  return { stops: tab.diff?.stops.kept ?? [], legs: tab.diff?.legs.kept ?? [] };
}

/** "Also remove these rows" applies only where the commit updates the trip in place. */
export function canRemoveMissing(tab: SheetTabOut): boolean {
  const kept = keptRows(tab);
  return tab.outcome === "update" && !tab.committed && kept.stops.length + kept.legs.length > 0;
}

/** The commit body: the chosen tabs, every tab's `trip_updated_at` as seen in this preview (a
 * newer one on the server is a 409), and the ticked options, limited to the chosen tabs. */
export function commitBody(preview: TripSheetPreviewOut, choices: Choices): TripSheetCommitIn {
  const chosen = preview.tabs.filter((tab) => included(tab, choices));
  const ids = new Set(chosen.map((tab) => tab.record_id));
  const pick = (set: Set<number>) => [...set].filter((id) => ids.has(id)).sort((a, b) => a - b);
  return {
    records: chosen.map((tab) => tab.record_id),
    seen: chosen.map((tab) => ({
      record_id: tab.record_id,
      trip_updated_at: tab.trip_updated_at,
    })),
    create_people: pick(choices.createPeople),
    recreate: pick(choices.recreate),
    remove_missing: pick(choices.removeMissing),
  };
}

// --- The problem report (§28.7) ---------------------------------------------------------------

export const REPORT_COLUMNS = ["tab", "row", "column", "severity", "reason", "message", "hint"];

/** "C (Place)", as the CLI's report writes it. */
export function columnLabel(issue: Pick<SheetIssueOut, "column" | "header">): string {
  if (issue.column && issue.header) return `${issue.column} (${issue.header})`;
  return issue.column || issue.header || "";
}

function csvCell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** The CSV the "Download report" button saves: workbook issues first, then each tab's by row. */
export function reportCsv(preview: TripSheetPreviewOut): string {
  const issues = [
    ...preview.workbook_issues,
    ...preview.tabs.flatMap((tab) => [...tab.issues].sort((a, b) => (a.row ?? 0) - (b.row ?? 0))),
  ];
  const lines = [REPORT_COLUMNS.join(",")];
  for (const issue of issues) {
    lines.push(
      [
        issue.tab,
        issue.row,
        columnLabel(issue),
        issue.severity,
        issue.reason,
        issue.message,
        issue.hint,
      ]
        .map(csvCell)
        .join(","),
    );
  }
  return `${lines.join("\r\n")}\r\n`;
}

export function reportName(originalName: string | null | undefined, batchId: number): string {
  const stem = (originalName ?? "").replace(/\.xlsx$/i, "").trim();
  return `${stem || `trip-sheet-${batchId}`}-report.csv`;
}

export function issueCounts(preview: TripSheetPreviewOut) {
  const all = [...preview.workbook_issues, ...preview.tabs.flatMap((tab) => tab.issues)];
  return {
    problems: all.filter((i) => i.severity === "problem").length,
    warnings: all.filter((i) => i.severity === "warning").length,
    total: all.length,
  };
}

// --- Map --------------------------------------------------------------------------------------

export type SheetStopProps = { record_id: number; row: number; name: string };
export type SheetLegProps = { record_id: number; row: number; mode: string };

export function sheetStopFeatures(tabs: SheetTabOut[]): FeatureCollection<Point, SheetStopProps> {
  return {
    type: "FeatureCollection",
    features: tabs.flatMap((tab) =>
      tab.stops.map((stop) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [stop.lon, stop.lat] },
        properties: { record_id: tab.record_id, row: stop.row, name: stop.name },
      })),
    ),
  };
}

/** Legs with both ends known, straight (great-circle for flights): the sheet has no routes. */
export function sheetLegFeatures(
  tabs: SheetTabOut[],
): FeatureCollection<LineString, SheetLegProps> {
  return {
    type: "FeatureCollection",
    features: tabs.flatMap((tab) =>
      tab.legs.flatMap((leg) => {
        const [a, b] = [leg.origin, leg.destination];
        if (!a || !b || a.length < 2 || b.length < 2) return [];
        const mode = leg.mode ?? "other";
        const coordinates: Position[] = mode === "flight" ? greatCircle(a, b) : [a, b];
        return [
          {
            type: "Feature" as const,
            geometry: { type: "LineString" as const, coordinates },
            properties: { record_id: tab.record_id, row: leg.row, mode },
          },
        ];
      }),
    ),
  };
}

export type Bounds = [[number, number], [number, number]];

/** The box around the given tabs' stops and legs, or null when there is nothing to draw. */
export function sheetBounds(tabs: SheetTabOut[]): Bounds | null {
  const points: Position[] = [
    ...sheetStopFeatures(tabs).features.map((f) => f.geometry.coordinates),
    ...sheetLegFeatures(tabs).features.flatMap((f) => f.geometry.coordinates),
  ];
  if (!points.length) return null;
  const lons = points.map((p) => p[0] ?? 0);
  const lats = points.map((p) => p[1] ?? 0);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}
