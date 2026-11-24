/** URL builders for the catalog pages (relative to the `/app` basename). Pages and map layers
 * use these instead of string literals, so a route can move in one place. */
import { matchPath } from "react-router";

export const paths = {
  list: "/trips",
  create: "/trips/new",
  trip: (tripId: number) => `/trips/${tripId}`,
  edit: (tripId: number) => `/trips/${tripId}/edit`,
  /** The leg's route view; the routing editor (items 25-26) mounts here. */
  legRoute: (tripId: number, legId: number) => `/trips/${tripId}/legs/${legId}/route`,
  tags: "/tags",
  purposes: "/purposes",
  people: "/people",
};

/** The trip a URL is about (`/trips/12`, `/trips/12/edit`, …), else null. */
export function selectedTripId(pathname: string): number | null {
  const match = matchPath({ path: "/trips/:tripId/*" }, pathname);
  const id = Number(match?.params.tripId);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** The leg whose route view is open (`/trips/12/legs/34/route`), else null. */
export function selectedLegId(pathname: string): number | null {
  const match = matchPath({ path: "/trips/:tripId/legs/:legId/route" }, pathname);
  const id = Number(match?.params.legId);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** Map home and trip pages show the trips layer. */
export function showsTrips(pathname: string): boolean {
  return pathname === "/" || pathname === "/trips" || pathname.startsWith("/trips/");
}
