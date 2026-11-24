import { useSearchParams } from "react-router";
import {
  type TravelMode,
  type TripStatus,
  useListPersons,
  useListPurposes,
  useListTags,
  type Visibility,
} from "../api/generated";
import { useShellMode } from "../shells/useShellMode";
import { inputClass } from "../ui/form";
import {
  EMPTY_FILTER,
  isFiltered,
  readTripFilter,
  type TripFilter,
  writeTripFilter,
} from "./filter";
import { MODE_LABELS, MODES, STATUS_LABELS, VISIBILITY_LABELS } from "./labels";
import { useFollowedText } from "./useFollowedText";

function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

const chip = (on: boolean) =>
  `rounded-full border px-2 py-0.5 text-xs ${on ? "border-blue-700 bg-blue-700 text-white" : "hover:bg-slate-100"}`;

/**
 * The mobile shell's title search (the desktop one is in the header). It keeps its own text,
 * like the header box (21a), so letters typed faster than the URL updates aren't dropped.
 */
export function TitleSearch({ q, onSearch }: { q: string; onSearch: (q: string) => void }) {
  const [text, setText] = useFollowedText(q);
  return (
    <input
      type="search"
      aria-label="Search trip titles"
      placeholder="Search titles…"
      className={inputClass}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onSearch(e.target.value);
      }}
    />
  );
}

/** Filters for the trip list and map; they edit the URL (see filter.ts). */
export function TripFilters() {
  const [params, setParams] = useSearchParams();
  const filter = readTripFilter(params);
  const purposes = useListPurposes();
  const tags = useListTags();
  const persons = useListPersons();
  // The desktop shell's header search box edits the same `q` (and "/" focuses it).
  const { mode: shell } = useShellMode();
  const update = (change: Partial<TripFilter>) =>
    setParams(writeTripFilter(params, { ...filter, ...change }), { replace: true });

  return (
    <section aria-label="Trip filters" className="mb-3 space-y-2 text-sm">
      {shell === "mobile" && <TitleSearch q={filter.q} onSearch={(q) => update({ q })} />}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-xs">
          From
          <input
            type="date"
            className="rounded border px-1 py-0.5 text-sm"
            value={filter.from ?? ""}
            onChange={(e) => update({ from: e.target.value || null })}
          />
        </label>
        <label className="flex flex-col text-xs">
          To
          <input
            type="date"
            className="rounded border px-1 py-0.5 text-sm"
            value={filter.to ?? ""}
            onChange={(e) => update({ to: e.target.value || null })}
          />
        </label>
        <label className="flex flex-col text-xs">
          Person
          <select
            className="rounded border px-1 py-0.5 text-sm"
            value={filter.person ?? ""}
            onChange={(e) => update({ person: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">Anyone</option>
            {(persons.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs">
          Visibility
          <select
            className="rounded border px-1 py-0.5 text-sm"
            value={filter.visibility ?? ""}
            onChange={(e) => update({ visibility: (e.target.value || null) as Visibility | null })}
          >
            <option value="">Any</option>
            {(Object.keys(VISIBILITY_LABELS) as Visibility[]).map((v) => (
              <option key={v} value={v}>
                {VISIBILITY_LABELS[v]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs">
          Status
          <select
            className="rounded border px-1 py-0.5 text-sm"
            value={filter.status ?? ""}
            onChange={(e) => update({ status: (e.target.value || null) as TripStatus | null })}
          >
            <option value="">Any</option>
            {(Object.keys(STATUS_LABELS) as TripStatus[]).map((v) => (
              <option key={v} value={v}>
                {STATUS_LABELS[v]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs">
          <input
            type="checkbox"
            checked={filter.inView}
            onChange={(e) => update({ inView: e.target.checked })}
          />
          Only in map view
        </label>
      </div>
      <fieldset className="flex flex-wrap gap-1">
        <legend className="sr-only">Travel mode</legend>
        {MODES.map((mode: TravelMode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={filter.mode.includes(mode)}
            className={chip(filter.mode.includes(mode))}
            onClick={() => update({ mode: toggle(filter.mode, mode) })}
          >
            {MODE_LABELS[mode]}
          </button>
        ))}
      </fieldset>
      {!!purposes.data?.length && (
        <fieldset className="flex flex-wrap gap-1">
          <legend className="sr-only">Purpose</legend>
          {purposes.data
            .filter((p) => !p.archived)
            .map((p) => (
              <button
                key={p.id}
                type="button"
                aria-pressed={filter.purpose.includes(p.id)}
                className={chip(filter.purpose.includes(p.id))}
                onClick={() => update({ purpose: toggle(filter.purpose, p.id) })}
              >
                {p.name}
              </button>
            ))}
        </fieldset>
      )}
      {!!tags.data?.length && (
        <fieldset className="flex flex-wrap gap-1">
          <legend className="sr-only">Tags</legend>
          {tags.data.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-pressed={filter.tag.includes(t.id)}
              className={chip(filter.tag.includes(t.id))}
              onClick={() => update({ tag: toggle(filter.tag, t.id) })}
            >
              #{t.name}
            </button>
          ))}
        </fieldset>
      )}
      {isFiltered(filter) && (
        <button
          type="button"
          className="text-xs text-blue-700 hover:underline"
          onClick={() => update(EMPTY_FILTER)}
        >
          Clear filters
        </button>
      )}
    </section>
  );
}
