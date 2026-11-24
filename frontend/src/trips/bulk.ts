/** Pure helpers for the trip list's bulk bar (`POST /trips/bulk`, D-89: all or nothing). */
import { ApiError } from "../api/client";
import type { BulkRefusalOut, PurposeOut } from "../api/generated";

/** The API takes at most this many trips per bulk request (`BulkTripsIn.trip_ids`). */
export const MAX_BULK = 500;

/** The trips a 403 refused, with the server's reason for each (empty for any other error). */
export function refusals(error: unknown): BulkRefusalOut[] {
  if (!(error instanceof ApiError) || error.status !== 403) return [];
  const body = error.body as { refused?: unknown } | undefined;
  if (!Array.isArray(body?.refused)) return [];
  return body.refused.filter(
    (r): r is BulkRefusalOut =>
      typeof r === "object" &&
      r !== null &&
      typeof (r as BulkRefusalOut).trip_id === "number" &&
      typeof (r as BulkRefusalOut).reason === "string",
  );
}

/** Purposes in the order `1`-`7` pick them: active ones, by their sort order. */
export function purposeKeys(purposes: PurposeOut[] | undefined): PurposeOut[] {
  return (purposes ?? [])
    .filter((p) => !p.archived)
    .sort((a, b) => a.sort - b.sort || a.id - b.id)
    .slice(0, 7);
}

/** "1 trip" / "3 trips". */
export function trips(n: number): string {
  return n === 1 ? "1 trip" : `${n.toLocaleString()} trips`;
}
