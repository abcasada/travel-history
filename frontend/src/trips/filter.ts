/**
 * The trip list's filter lives in the URL (`/trips?q=lake&purpose=3&mode=drive&mode=flight`), so
 * the list pane that edits it and the map that draws the same trips share one source of truth,
 * and a filtered view can be bookmarked. Repeated parameters mean any-of (the API's rule).
 */
import type { GetTripMapParams, ListTripsParams, TravelMode, Visibility } from "../api/generated";

export type TripFilter = {
  q: string;
  from: string | null;
  to: string | null;
  purpose: number[];
  tag: number[];
  mode: TravelMode[];
  /** Trips this person is on (the API takes one). */
  person: number | null;
  visibility: Visibility | null;
  /** Only trips with something inside the current map view (`bbox` from the map store). */
  inView: boolean;
};

export const EMPTY_FILTER: TripFilter = {
  q: "",
  from: null,
  to: null,
  purpose: [],
  tag: [],
  mode: [],
  person: null,
  visibility: null,
  inView: false,
};

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MODES = new Set(["drive", "flight", "train", "bus", "boat", "walk", "other"]);
const VISIBILITIES = new Set(["private", "participants", "family", "public"]);

function ids(params: URLSearchParams, key: string): number[] {
  return params
    .getAll(key)
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0);
}

export function readTripFilter(params: URLSearchParams): TripFilter {
  const day = (key: string) => {
    const value = params.get(key);
    return value && DAY.test(value) ? value : null;
  };
  return {
    q: params.get("q") ?? "",
    from: day("from"),
    to: day("to"),
    purpose: ids(params, "purpose"),
    tag: ids(params, "tag"),
    mode: params.getAll("mode").filter((m) => MODES.has(m)) as TravelMode[],
    person: ids(params, "person")[0] ?? null,
    visibility: VISIBILITIES.has(params.get("visibility") ?? "")
      ? (params.get("visibility") as Visibility)
      : null,
    inView: params.get("in_view") === "1",
  };
}

const FILTER_KEYS = [
  "q",
  "from",
  "to",
  "purpose",
  "tag",
  "mode",
  "person",
  "visibility",
  "in_view",
];

/** New search params with the filter applied (other params are kept). */
export function writeTripFilter(params: URLSearchParams, filter: TripFilter): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of FILTER_KEYS) next.delete(key);
  if (filter.q.trim()) next.set("q", filter.q);
  if (filter.from) next.set("from", filter.from);
  if (filter.to) next.set("to", filter.to);
  for (const id of filter.purpose) next.append("purpose", String(id));
  for (const id of filter.tag) next.append("tag", String(id));
  for (const mode of filter.mode) next.append("mode", mode);
  if (filter.person !== null) next.set("person", String(filter.person));
  if (filter.visibility) next.set("visibility", filter.visibility);
  if (filter.inView) next.set("in_view", "1");
  return next;
}

export function isFiltered(filter: TripFilter): boolean {
  return JSON.stringify(filter) !== JSON.stringify(EMPTY_FILTER);
}

/** API parameters for `listTrips` / `getTripMap`. `bbox` comes from the map's current view. */
export function apiParams(filter: TripFilter, bbox?: string | null): GetTripMapParams {
  const params: ListTripsParams = {};
  if (filter.q.trim()) params.q = filter.q.trim();
  if (filter.from) params.from = filter.from;
  if (filter.to) params.to = filter.to;
  if (filter.purpose.length) params.purpose = filter.purpose;
  if (filter.tag.length) params.tag = filter.tag;
  if (filter.mode.length) params.mode = filter.mode;
  if (filter.person !== null) params.person = filter.person;
  if (filter.visibility) params.visibility = filter.visibility;
  if (filter.inView && bbox) params.bbox = bbox;
  return params;
}
