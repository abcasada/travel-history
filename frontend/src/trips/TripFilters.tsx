import { useSearchParams } from "react-router";
import { type TravelMode, useListPurposes, useListTags } from "../api/generated";
import { inputClass } from "../ui/form";
import {
  EMPTY_FILTER,
  isFiltered,
  readTripFilter,
  type TripFilter,
  writeTripFilter,
} from "./filter";
import { MODE_LABELS, MODES } from "./labels";

function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

const chip = (on: boolean) =>
  `rounded-full border px-2 py-0.5 text-xs ${on ? "border-blue-700 bg-blue-700 text-white" : "hover:bg-slate-100"}`;

/** Filters for the trip list and map; they edit the URL (see filter.ts). */
export function TripFilters() {
  const [params, setParams] = useSearchParams();
  const filter = readTripFilter(params);
  const purposes = useListPurposes();
  const tags = useListTags();
  const update = (change: Partial<TripFilter>) =>
    setParams(writeTripFilter(params, { ...filter, ...change }), { replace: true });

  return (
    <section aria-label="Trip filters" className="mb-3 space-y-2 text-sm">
      <input
        type="search"
        aria-label="Search trip titles"
        placeholder="Search titles…"
        className={inputClass}
        value={filter.q}
        onChange={(e) => update({ q: e.target.value })}
      />
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
