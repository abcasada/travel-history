import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  type BulkTripsIn,
  getListTagsQueryKey,
  type TripOut,
  useBulkEditTrips,
  useCreateTag,
  useListPersons,
  useListPurposes,
  useListTags,
  type Visibility,
} from "../api/generated";
import { MutationError } from "../ui/QueryState";
import { MAX_BULK, purposeKeys, refusals, trips } from "./bulk";
import { invalidateTrips } from "./cache";
import { EDITABLE_VISIBILITIES, label, VISIBILITY_LABELS } from "./labels";

export type BulkPanel = "tag" | "purpose" | "people" | "visibility";

const PANELS: { id: BulkPanel; label: string; key: string }[] = [
  { id: "tag", label: "Tag", key: "t" },
  { id: "purpose", label: "Purpose", key: "u" },
  { id: "people", label: "People", key: "p" },
  { id: "visibility", label: "Visibility", key: "" },
];

const select = "rounded border px-1 py-0.5 text-sm";
const action =
  "rounded bg-blue-700 px-2 py-0.5 text-sm text-white hover:bg-blue-800 disabled:opacity-50";

/** Run one bulk change; the list and map refresh and the outcome is reported in the bar. */
export function useBulkChange(tripIds: number[]) {
  const client = useQueryClient();
  const mutation = useBulkEditTrips();
  const [done, setDone] = useState<string | null>(null);
  const runFor = (ids: number[], change: Omit<BulkTripsIn, "trip_ids">, what: string) => {
    setDone(null);
    mutation.mutate(
      { data: { trip_ids: ids, ...change } },
      {
        onSuccess: async () => {
          await invalidateTrips(client, ids);
          if (change.add_tag_ids || change.remove_tag_ids)
            await client.invalidateQueries({ queryKey: getListTagsQueryKey() });
          setDone(`${what}: ${trips(ids.length)} updated.`);
        },
      },
    );
  };
  const run = (change: Omit<BulkTripsIn, "trip_ids">, what: string) =>
    runFor(tripIds, change, what);
  return { run, runFor, mutation, done };
}

/**
 * The bar shown while trips are selected (ui.md §18.4, frontend-patterns.md §8): tag, purpose,
 * people and visibility for every selected trip at once. The server applies a change to all of
 * them or to none (D-89); when it refuses, each refused trip is listed with the reason.
 */
export function BulkBar({
  tripIds,
  listed,
  panel,
  setPanel,
  change,
  onClear,
}: {
  tripIds: number[];
  /** The loaded trips, to name refused ones. */
  listed: TripOut[];
  panel: BulkPanel | null;
  setPanel: (panel: BulkPanel | null) => void;
  change: ReturnType<typeof useBulkChange>;
  onClear: () => void;
}) {
  const tooMany = tripIds.length > MAX_BULK;
  const refused = refusals(change.mutation.error);
  const titles = new Map(listed.map((t) => [t.id, t.title]));
  return (
    <section
      aria-label="Selected trips"
      className="sticky top-0 z-10 mb-2 space-y-2 rounded border border-blue-200 bg-blue-50 p-2 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium" aria-live="polite">
          {tripIds.length.toLocaleString()} selected
        </span>
        {PANELS.map((p) => (
          <button
            key={p.id}
            type="button"
            aria-pressed={panel === p.id}
            className={`rounded border px-2 py-0.5 ${panel === p.id ? "border-blue-700 bg-white" : "bg-white/60 hover:bg-white"}`}
            onClick={() => setPanel(panel === p.id ? null : p.id)}
            title={p.key ? `Shortcut: ${p.key}` : undefined}
          >
            {p.label}
          </button>
        ))}
        <button type="button" className="ml-auto text-blue-700 hover:underline" onClick={onClear}>
          Clear selection
        </button>
      </div>
      {tooMany && (
        <p className="text-amber-800">
          Select at most {MAX_BULK} trips for one change ({tripIds.length.toLocaleString()} are
          selected).
        </p>
      )}
      {panel === "tag" && <TagPanel change={change} disabled={tooMany} />}
      {panel === "purpose" && <PurposePanel change={change} disabled={tooMany} />}
      {panel === "people" && <PeoplePanel change={change} disabled={tooMany} />}
      {panel === "visibility" && <VisibilityPanel change={change} disabled={tooMany} />}
      {change.done && <p role="status">{change.done}</p>}
      {refused.length > 0 ? (
        <div role="alert" className="text-red-700">
          <p>Nothing was changed. {trips(refused.length)} can't take this change:</p>
          <ul className="ml-4 list-disc">
            {refused.map((r) => (
              <li key={r.trip_id}>
                {titles.get(r.trip_id) ?? `Trip ${r.trip_id}`}: {r.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <MutationError error={change.mutation.error} what="change" />
      )}
    </section>
  );
}

/** A panel opened with t/u/p puts the keyboard in its first field (a stable callback ref, so it
 * runs once when the panel mounts; the autoFocus attribute is linted out). */
function focusOnMount(element: HTMLSelectElement | null) {
  element?.focus();
}

type PanelProps = { change: ReturnType<typeof useBulkChange>; disabled: boolean };

function TagPanel({ change, disabled }: PanelProps) {
  const client = useQueryClient();
  const tags = useListTags();
  const create = useCreateTag();
  const [tagId, setTagId] = useState("");
  const [name, setName] = useState("");
  const busy = disabled || change.mutation.isPending || create.isPending;

  const add = async () => {
    let id = Number(tagId);
    if (!id && name.trim()) {
      id = (await create.mutateAsync({ data: { name: name.trim() } })).id;
      await client.invalidateQueries({ queryKey: getListTagsQueryKey() });
      setName("");
    }
    if (id) change.run({ add_tag_ids: [id] }, "Tag added");
  };

  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col text-xs">
        Your tag
        <select
          ref={focusOnMount}
          className={select}
          value={tagId}
          onChange={(e) => setTagId(e.target.value)}
        >
          <option value="">New tag…</option>
          {(tags.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              #{t.name}
            </option>
          ))}
        </select>
      </label>
      {!tagId && (
        <label className="flex flex-col text-xs">
          New tag name
          <input
            className={select}
            value={name}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void add().catch(() => {});
            }}
          />
        </label>
      )}
      <button
        type="button"
        className={action}
        disabled={busy || (!tagId && !name.trim())}
        onClick={() => void add().catch(() => {})}
      >
        Add tag
      </button>
      {tagId && (
        <button
          type="button"
          className="rounded border bg-white px-2 py-0.5 hover:bg-slate-100 disabled:opacity-50"
          disabled={busy}
          onClick={() => change.run({ remove_tag_ids: [Number(tagId)] }, "Tag removed")}
        >
          Remove tag
        </button>
      )}
      <MutationError error={create.error} what="tag" />
    </div>
  );
}

function PurposePanel({ change, disabled }: PanelProps) {
  const purposes = useListPurposes();
  const keyed = purposeKeys(purposes.data);
  const [value, setValue] = useState("");
  const busy = disabled || change.mutation.isPending;
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col text-xs">
        Purpose
        <select
          ref={focusOnMount}
          className={select}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        >
          <option value="">Choose…</option>
          {keyed.map((p, i) => (
            <option key={p.id} value={p.id}>
              {i + 1}. {p.name}
            </option>
          ))}
          <option value="none">No purpose</option>
        </select>
      </label>
      <button
        type="button"
        className={action}
        disabled={busy || !value}
        onClick={() =>
          change.run(
            { purpose_id: value === "none" ? null : Number(value) },
            value === "none" ? "Purpose cleared" : "Purpose set",
          )
        }
      >
        Set purpose
      </button>
      <span className="text-xs text-slate-600">Or press 1-{keyed.length || 7} in the list.</span>
    </div>
  );
}

function PeoplePanel({ change, disabled }: PanelProps) {
  const persons = useListPersons();
  const [value, setValue] = useState("");
  const busy = disabled || change.mutation.isPending || !value;
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col text-xs">
        Person
        <select
          ref={focusOnMount}
          className={select}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        >
          <option value="">Choose…</option>
          {(persons.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className={action}
        disabled={busy}
        onClick={() => change.run({ add_person_ids: [Number(value)] }, "Person added")}
      >
        Add to trips
      </button>
      <button
        type="button"
        className="rounded border bg-white px-2 py-0.5 hover:bg-slate-100 disabled:opacity-50"
        disabled={busy}
        onClick={() => change.run({ remove_person_ids: [Number(value)] }, "Person removed")}
      >
        Remove from trips
      </button>
    </div>
  );
}

function VisibilityPanel({ change, disabled }: PanelProps) {
  const [value, setValue] = useState<Visibility | "">("");
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col text-xs">
        Visibility
        <select
          ref={focusOnMount}
          className={select}
          value={value}
          onChange={(e) => setValue(e.target.value as Visibility | "")}
        >
          <option value="">Choose…</option>
          {EDITABLE_VISIBILITIES.map((v) => (
            <option key={v} value={v}>
              {label(VISIBILITY_LABELS, v)}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className={action}
        disabled={disabled || change.mutation.isPending || !value}
        onClick={() => value && change.run({ visibility: value }, "Visibility set")}
      >
        Set visibility
      </button>
    </div>
  );
}
