import { Link } from "react-router";
import type {
  SheetDiffOut,
  SheetFieldChangeOut,
  SheetIssueOut,
  SheetRowOut,
  SheetTabOut,
} from "../api/generated";
import { label, MODE_LABELS } from "../trips/labels";
import { paths } from "../trips/paths";
import {
  blockedOnlyByUnknownPeople,
  type Choices,
  canRemoveMissing,
  columnLabel,
  importable,
  included,
  keptRows,
  OUTCOME_TONES,
  outcomeLabel,
  toggled,
} from "./sheet";

const FIELD_LABELS: Record<string, string> = {
  title: "Title",
  start_date: "Start",
  end_date: "End",
  date_precision: "Date precision",
  purpose_id: "Purpose",
  visibility: "Visibility",
  notes: "Notes",
  place: "Place",
  kind: "Kind",
  arrive_utc: "Arrive",
  depart_utc: "Depart",
  tz: "Time zone",
  time_precision: "Time precision",
  mode: "Mode",
  origin: "From",
  destination: "To",
  start_utc: "Depart",
  end_utc: "Arrive",
  start_tz: "Depart zone",
  end_tz: "Arrive zone",
  origin_label: "From name",
  destination_label: "To name",
  origin_airport_id: "From airport",
  destination_airport_id: "To airport",
  airline_id: "Airline",
  flight_number: "Flight",
  aircraft_type_id: "Aircraft",
  aircraft_registration: "Registration",
  seat: "Seat",
  cabin_class: "Cabin",
  vehicle_id: "Vehicle",
};

const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]00:00)$/;

/** A diff value as text: UTC instants in UTC (the sheet's local times were converted with
 * the zone shown next to them), empty values as a dash. */
export function formatValue(value: SheetFieldChangeOut["old"]): string {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "string" && ISO_UTC.test(value)) {
    return `${value.slice(0, 10)} ${value.slice(11, 16)} UTC`;
  }
  const text = String(value);
  return text.length > 80 ? `${text.slice(0, 77)}…` : text;
}

type Props = {
  tab: SheetTabOut;
  open: boolean;
  batchOpen: boolean;
  choices: Choices;
  onChoices: (next: Choices) => void;
  onShowOnMap: () => void;
};

/** One tab of the workbook: what importing it would do, its problems and its diff (§28.8). */
export function TabCard({ tab, open, batchOpen, choices, onChoices, onShowOnMap }: Props) {
  const id = tab.record_id;
  const editable = batchOpen && !tab.committed;
  const tone = OUTCOME_TONES[tab.committed ? "identical" : tab.outcome] ?? OUTCOME_TONES.identical;
  const kept = keptRows(tab);
  const keptCount = kept.stops.length + kept.legs.length;
  const set = (key: keyof Choices, on: boolean) =>
    onChoices({ ...choices, [key]: toggled(choices[key], id, on) });

  return (
    <section
      aria-label={`Tab ${tab.tab}`}
      data-record-id={id}
      className={`mb-4 rounded border p-3 ${open ? "border-blue-400 ring-1 ring-blue-200" : ""}`}
    >
      <div className="mb-1 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-medium break-words">{tab.title}</h3>
          <p className="text-xs text-slate-500">
            Tab “{tab.tab}” · key {tab.key}
            {tab.last_imported_at &&
              ` · last imported ${new Date(tab.last_imported_at).toLocaleDateString()}`}
          </p>
        </div>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone}`}>
          {outcomeLabel(tab)}
        </span>
      </div>
      <div className="mb-2 flex flex-wrap gap-3 text-sm">
        {(tab.stops.length > 0 || tab.legs.length > 0) && (
          <button type="button" className="text-blue-700 hover:underline" onClick={onShowOnMap}>
            Show on map
          </button>
        )}
        {tab.trip_id !== null && (
          <Link className="text-blue-700 hover:underline" to={paths.trip(tab.trip_id)}>
            Open the trip
          </Link>
        )}
      </div>

      {editable && (
        <div className="mb-2 space-y-1 text-sm">
          {importable(tab, choices) && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={included(tab, choices)}
                onChange={(e) => set("excluded", !e.target.checked)}
              />
              Import this tab
            </label>
          )}
          {tab.unknown_people.length > 0 && (
            <div>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={choices.createPeople.has(id)}
                  onChange={(e) => set("createPeople", e.target.checked)}
                />
                <span>
                  Create these people: {tab.unknown_people.join(", ")}
                  <span className="block text-xs text-slate-500">
                    New people are visible to the family, like people added in the app. Leave this
                    off if they already exist under another name and fix the sheet instead.
                  </span>
                </span>
              </label>
              {tab.outcome === "blocked" && !blockedOnlyByUnknownPeople(tab) && (
                <p className="ml-6 text-xs text-red-700">Other problems still block this tab.</p>
              )}
            </div>
          )}
          {tab.outcome === "deleted" && (
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={choices.recreate.has(id)}
                onChange={(e) => set("recreate", e.target.checked)}
              />
              <span>
                Re-create this trip
                <span className="block text-xs text-slate-500">
                  You deleted the trip this tab made, so it is skipped unless you tick this.
                </span>
              </span>
            </label>
          )}
          {canRemoveMissing(tab) && (
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={choices.removeMissing.has(id)}
                onChange={(e) => set("removeMissing", e.target.checked)}
              />
              <span>
                Also remove the {keptCount === 1 ? "stop or leg" : `${keptCount} stops and legs`}{" "}
                the sheet no longer has: {[...kept.stops, ...kept.legs].map(rowName).join("; ")}
              </span>
            </label>
          )}
        </div>
      )}
      {tab.outcome === "review" && !tab.committed && (
        <p className="mb-2 text-sm text-amber-800">
          You have edited this trip in the app since it was imported, so the sheet won't change it.
          Importing sends the changes below to the review queue instead.
        </p>
      )}
      {tab.outcome === "transferred" && !tab.committed && (
        <p className="mb-2 text-sm text-slate-600">
          The trip this tab made is no longer yours, so the tab is skipped.
        </p>
      )}

      {tab.issues.length > 0 && <IssueTable issues={tab.issues} caption={`Issues in ${tab.tab}`} />}
      {tab.diff && <DiffView diff={tab.diff} newTags={tab.new_tags} isNew={tab.trip_id === null} />}
    </section>
  );
}

function rowName(row: SheetRowOut): string {
  return row.mode ? `${label(MODE_LABELS, row.mode)} ${row.name}` : row.name;
}

const SEVERITY_TONES: Record<string, string> = {
  problem: "text-red-800",
  warning: "text-amber-800",
  info: "text-slate-600",
};

/** Issues by row, with the column and a fix: the hint, or the exact text for each candidate. */
export function IssueTable({ issues, caption }: { issues: SheetIssueOut[]; caption: string }) {
  return (
    <div className="mb-2 overflow-x-auto">
      <table className="w-full text-left text-sm" aria-label={caption}>
        <thead className="text-xs text-slate-500">
          <tr>
            <th className="py-1 pr-2 font-normal">Row</th>
            <th className="py-1 pr-2 font-normal">Column</th>
            <th className="py-1 font-normal">Issue</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr
              // Issues have no id; their order is the server's and stable for a record.
              // biome-ignore lint/suspicious/noArrayIndexKey: see above
              key={index}
              className="border-t align-top"
            >
              <td className="py-1 pr-2 whitespace-nowrap">{issue.row ?? "–"}</td>
              <td className="py-1 pr-2">{columnLabel(issue) || "–"}</td>
              <td className={`py-1 ${SEVERITY_TONES[issue.severity] ?? ""}`}>
                <span className="font-medium capitalize">{issue.severity}:</span> {issue.message}
                {issue.hint && <span className="block text-xs text-slate-600">{issue.hint}</span>}
                {issue.candidates.length > 0 && (
                  <span className="block text-xs text-slate-600">
                    {issue.reason === "unknown_person" ? "Can be created: " : "Did you mean: "}
                    {issue.candidates.map((c, i) => (
                      <span key={c}>
                        {i > 0 && ", "}
                        <code className="rounded bg-slate-100 px-1">{c}</code>
                      </span>
                    ))}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Changes({ changes }: { changes: SheetFieldChangeOut[] }) {
  return (
    <ul className="ml-4 text-xs text-slate-600">
      {changes.map((change) => (
        <li key={change.field}>
          {FIELD_LABELS[change.field] ?? change.field}: {formatValue(change.old)} →{" "}
          {formatValue(change.new)}
        </li>
      ))}
    </ul>
  );
}

function RowList({ title, rows, note }: { title: string; rows: SheetRowOut[]; note?: string }) {
  if (rows.length === 0) return null;
  return (
    <div className="mb-1">
      <p className="text-xs font-medium text-slate-700">
        {title} ({rows.length}){note && <span className="font-normal text-slate-500"> {note}</span>}
      </p>
      <ul className="ml-2 text-sm">
        {rows.map((row, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows have no single id across kinds
          <li key={index}>
            {row.row !== null && row.row !== undefined && (
              <span className="mr-1 text-xs text-slate-500">row {row.row}</span>
            )}
            {rowName(row)}
            {row.changes && row.changes.length > 0 && <Changes changes={row.changes} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Old → new for the trip's fields; stops and legs added, changed and kept (never deleted
 * unless the user asks, rule 6). */
function DiffView({
  diff,
  newTags,
  isNew,
}: {
  diff: SheetDiffOut;
  newTags: string[];
  isNew: boolean;
}) {
  const empty =
    diff.trip.length + diff.people_added.length + diff.tags_added.length === 0 &&
    [diff.stops, diff.legs].every((p) => p.added.length + p.changed.length + p.kept.length === 0);
  if (empty) return null;
  return (
    <details className="mt-1" open>
      <summary className="cursor-pointer text-sm font-medium">
        {isNew ? "What will be created" : "What changes"}
      </summary>
      <div className="mt-1 space-y-1">
        {diff.trip.length > 0 && (
          <div>
            <p className="text-xs font-medium text-slate-700">Trip</p>
            <Changes changes={diff.trip} />
          </div>
        )}
        {diff.people_added.length > 0 && (
          <p className="text-sm">People added: {diff.people_added.join(", ")}</p>
        )}
        {diff.tags_added.length > 0 && (
          <p className="text-sm">
            Tags added: {diff.tags_added.join(", ")}
            {newTags.length > 0 && (
              <span className="text-xs text-slate-500"> (new tags: {newTags.join(", ")})</span>
            )}
          </p>
        )}
        <RowList title={isNew ? "Stops" : "Stops added"} rows={diff.stops.added} />
        <RowList title="Stops changed" rows={diff.stops.changed} />
        <RowList title="Stops not in the sheet" rows={diff.stops.kept} note="(kept)" />
        <RowList title={isNew ? "Legs" : "Legs added"} rows={diff.legs.added} />
        <RowList title="Legs changed" rows={diff.legs.changed} />
        <RowList title="Legs not in the sheet" rows={diff.legs.kept} note="(kept)" />
      </div>
    </details>
  );
}
