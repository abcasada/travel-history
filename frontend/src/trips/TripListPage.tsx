import { keepPreviousData } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { type TripOut, useListTrips } from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { importPaths } from "../imports/paths";
import { formatDateRange } from "../lib/time";
import { useMapStore } from "../map/store";
import { QueryState } from "../ui/QueryState";
import { apiParams, isFiltered, readTripFilter } from "./filter";
import { label, VISIBILITY_LABELS } from "./labels";
import { paths } from "./paths";
import { TripFilters } from "./TripFilters";

// Paging and a virtualized list come with bulk selection (item 21); until then the newest
// PAGE_SIZE matching trips are listed and the count says if there are more.
const PAGE_SIZE = 200;

/** The trip list (map home and `/trips`): filters, then the newest matching trips. */
export function TripListPage({ title = "Trips" }: { title?: string }) {
  const me = useMe();
  const [params] = useSearchParams();
  const filter = readTripFilter(params);
  const bbox = useMapStore((s) => s.bbox);
  const query = useListTrips(
    { ...apiParams(filter, bbox), limit: PAGE_SIZE },
    { query: { placeholderData: keepPreviousData } },
  );
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        {me.role !== "viewer" && (
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
      <QueryState query={query} what="trip list">
        {(page) => (
          <>
            <p className="mb-2 text-xs text-slate-500" aria-live="polite">
              {page.count === 1 ? "1 trip" : `${page.count.toLocaleString()} trips`}
              {page.count > page.items.length && ` (newest ${page.items.length} shown)`}
            </p>
            {page.items.length === 0 ? (
              <p className="text-sm text-slate-600">
                {isFiltered(filter)
                  ? "No trips match these filters."
                  : "No trips yet. Add your first one with New trip."}
              </p>
            ) : (
              <ul className="divide-y rounded border">
                {page.items.map((trip) => (
                  <TripRow key={trip.id} trip={trip} />
                ))}
              </ul>
            )}
          </>
        )}
      </QueryState>
    </div>
  );
}

function TripRow({ trip }: { trip: TripOut }) {
  return (
    <li>
      <Link to={paths.trip(trip.id)} className="block px-3 py-2 hover:bg-slate-50">
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
