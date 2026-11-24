import { keepPreviousData, type UseQueryResult, useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import {
  getListTripsQueryKey,
  listTrips,
  type TripOut,
  type TripPageOut,
  useListPurposes,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { importPaths } from "../imports/paths";
import { formatDateRange } from "../lib/time";
import { useMapStore } from "../map/store";
import { isTypingTarget, useShortcuts } from "../platform/shortcuts";
import { QueryState } from "../ui/QueryState";
import { BulkBar, type BulkPanel, useBulkChange } from "./BulkBar";
import { purposeKeys, trips } from "./bulk";
import { apiParams, isFiltered, readTripFilter } from "./filter";
import { label, VISIBILITY_LABELS } from "./labels";
import { paths } from "./paths";
import { extend, moveCursor, prune, targets, toggle, useSelectionStore } from "./selection";
import { TripFilters } from "./TripFilters";

/** Trips per request; "Show more" loads the next page (the API allows up to 500). */
export const PAGE_SIZE = 200;

/** The matching trips so far: the total count and every loaded page's items, newest first. */
type Loaded = { count: number; items: TripOut[] };

/**
 * The list's pages. The key starts with the generated `listTrips` key, so `trips/cache.ts`
 * refreshes these pages with every other trip list after a change.
 */
function useTripPages(params: ReturnType<typeof apiParams>) {
  const request = { ...params, limit: PAGE_SIZE };
  return useInfiniteQuery({
    queryKey: [...getListTripsQueryKey(request), "pages"],
    queryFn: ({ pageParam, signal }) =>
      listTrips(pageParam ? { ...request, offset: pageParam } : request, { signal }),
    initialPageParam: 0,
    getNextPageParam: (last: TripPageOut, pages: TripPageOut[]) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0);
      return last.items.length && loaded < last.count ? loaded : undefined;
    },
    select: (data): Loaded => ({
      count: data.pages.at(-1)?.count ?? 0,
      items: data.pages.flatMap((page) => page.items),
    }),
    placeholderData: keepPreviousData,
  });
}

/**
 * The trip list (map home and `/trips`), a working tool (ui.md §18.4): filters; a keyboard
 * cursor (`j`/`k`, `Enter` opens, `e` edits); a selection (`x`, `Shift+j/k`, `*` then `a`/`n`)
 * that the map highlights and `f` fits; a bulk bar for the selection (`t`, `u`, `p`, `1`-`7`);
 * and pages of PAGE_SIZE trips. Both shells show it; the keys matter on the desktop.
 */
export function TripListPage({ title = "Trips" }: { title?: string }) {
  const me = useMe();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const filter = readTripFilter(params);
  const bbox = useMapStore((s) => s.bbox);
  const query = useTripPages(apiParams(filter, bbox));
  const items = query.data?.items;
  const ids = useMemo(() => (items ?? []).map((t) => t.id), [items]);
  const selection = useSelectionStore();
  const purposes = useListPurposes();
  const [panel, setPanel] = useState<BulkPanel | null>(null);
  const change = useBulkChange(selection.selected);
  const canEdit = me.role !== "viewer";

  // A new filter drops selected trips it no longer lists (once its results are in).
  useEffect(() => {
    if (items && !query.isPlaceholderData) useSelectionStore.getState().apply((s) => prune(s, ids));
  }, [items, ids, query.isPlaceholderData]);

  useEffect(() => {
    if (!selection.selected.length) setPanel(null);
  }, [selection.selected.length]);

  /** With nothing selected, the bulk keys act on the cursor's trip (selecting it first). */
  const selectCursorIfNone = (): number[] => {
    const state = useSelectionStore.getState();
    if (!state.selected.length && state.cursor !== null) state.apply((s) => toggle(s, s.cursor));
    return targets(useSelectionStore.getState());
  };
  const openPanel = (next: BulkPanel) => {
    if (canEdit && selectCursorIfNone().length) setPanel(next);
  };
  const setPurposeByKey = (n: number) => {
    const purpose = purposeKeys(purposes.data)[n - 1];
    if (!canEdit || !purpose) return;
    const ids = selectCursorIfNone();
    if (ids.length)
      change.runFor(ids, { purpose_id: purpose.id }, `Purpose set to ${purpose.name}`);
  };
  const open = (to: (id: number) => string) =>
    selection.cursor !== null && navigate(to(selection.cursor));

  useShortcuts(
    {
      j: () => selection.apply((s) => moveCursor(s, ids, 1)),
      k: () => selection.apply((s) => moveCursor(s, ids, -1)),
      J: () => selection.apply((s) => extend(s, ids, 1)),
      K: () => selection.apply((s) => extend(s, ids, -1)),
      x: () => selection.apply((s) => toggle(s, s.cursor)),
      Enter: () => open(paths.trip),
      o: () => open(paths.trip),
      e: () => open(paths.edit),
      "* a": () => selection.selectAll(ids),
      "* n": () => selection.clear(),
      f: () => selection.requestFit(),
      t: () => openPanel("tag"),
      u: () => openPanel("purpose"),
      p: () => openPanel("people"),
      ...Object.fromEntries(
        [1, 2, 3, 4, 5, 6, 7].map((n) => [String(n), () => setPurposeByKey(n)]),
      ),
      Escape: (event) => {
        if (panel) {
          setPanel(null);
          if (event.target instanceof HTMLElement) event.target.blur();
        } else if (!isTypingTarget(event.target)) selection.clear();
      },
    },
    ids.length > 0,
  );

  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        {canEdit && (
          <div className="flex items-center gap-3">
            <Link to={importPaths.list} className="text-sm text-blue-700 hover:underline">
              Import
            </Link>
            <Link
              to={paths.create}
              className="rounded-md bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800"
            >
              New trip
            </Link>
          </div>
        )}
      </div>
      <TripFilters />
      {canEdit && selection.selected.length > 0 && (
        <BulkBar
          tripIds={selection.selected}
          listed={items ?? []}
          panel={panel}
          setPanel={setPanel}
          change={change}
          onClear={selection.clear}
        />
      )}
      <QueryState query={query as UseQueryResult<Loaded>} what="trip list">
        {(page) => (
          <>
            <p className="mb-2 text-xs text-slate-500" aria-live="polite">
              {trips(page.count)}
              {page.count > page.items.length &&
                ` (newest ${page.items.length.toLocaleString()} shown)`}
            </p>
            {page.items.length === 0 ? (
              <p className="text-sm text-slate-600">
                {isFiltered(filter)
                  ? "No trips match these filters."
                  : "No trips yet. Add your first one with New trip."}
              </p>
            ) : (
              <ul className="divide-y rounded border" aria-label="Trips">
                {page.items.map((trip) => (
                  <TripRow
                    key={trip.id}
                    trip={trip}
                    isCursor={selection.cursor === trip.id}
                    isSelected={selection.selected.includes(trip.id)}
                    selectable={canEdit}
                    onToggle={() =>
                      selection.apply((s) => ({ ...toggle(s, trip.id), cursor: trip.id }))
                    }
                  />
                ))}
              </ul>
            )}
            {query.hasNextPage && (
              <button
                type="button"
                className="mt-2 w-full rounded border py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
                disabled={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage()}
              >
                {query.isFetchingNextPage
                  ? "Loading…"
                  : `Show ${Math.min(PAGE_SIZE, page.count - page.items.length).toLocaleString()} more`}
              </button>
            )}
          </>
        )}
      </QueryState>
    </div>
  );
}

function TripRow({
  trip,
  isCursor,
  isSelected,
  selectable,
  onToggle,
}: {
  trip: TripOut;
  isCursor: boolean;
  isSelected: boolean;
  selectable: boolean;
  onToggle: () => void;
}) {
  const ref = useRef<HTMLLIElement>(null);
  // Keep the cursor's row in view as j/k move it (jsdom has no scrollIntoView).
  useEffect(() => {
    if (isCursor) ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [isCursor]);
  return (
    <li
      ref={ref}
      aria-current={isCursor ? "true" : undefined}
      data-trip-id={trip.id}
      className={`flex items-start gap-2 px-3 ${isSelected ? "bg-blue-50" : ""} ${isCursor ? "shadow-[inset_3px_0_0_0] shadow-blue-600" : ""}`}
    >
      {selectable && (
        <input
          type="checkbox"
          className="mt-3"
          aria-label={`Select ${trip.title}`}
          checked={isSelected}
          onChange={onToggle}
        />
      )}
      <Link to={paths.trip(trip.id)} className="block min-w-0 flex-1 py-2 hover:bg-slate-50">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-medium">{trip.title}</span>
          <span className="shrink-0 text-xs text-slate-500">
            {formatDateRange(trip.start_date, trip.end_date)}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-slate-600">
          {trip.purpose && <span>{trip.purpose.name}</span>}
          <span>{label(VISIBILITY_LABELS, trip.visibility)}</span>
          {!trip.is_owner && <span>by {trip.owner.display_name}</span>}
          {trip.needs_review && <span className="text-amber-700">needs review</span>}
          {trip.tags.map((t) => (
            <span key={`${t.id}-${t.author.id}`} className="text-blue-800">
              #{t.name}
            </span>
          ))}
        </div>
      </Link>
    </li>
  );
}
