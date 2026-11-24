/**
 * After a change to a trip (or anything on it), refresh exactly what can show it: its detail,
 * every trip list page and the trip map, whatever their filters. Mutations call this in their
 * onSuccess; nothing else touches the trips' cached queries (frontend-patterns.md, "Data").
 */
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  getGetTripMapQueryKey,
  getGetTripQueryKey,
  getListNotesQueryKey,
  getListTagsQueryKey,
  getListTripsQueryKey,
  getListTripTagsQueryKey,
} from "../api/generated";

export function invalidateTrip(client: QueryClient, tripId?: number) {
  // Own tags' trip counts change with tagging, so the tag list is refreshed too.
  const keys: readonly unknown[][] = [
    [...getListTripsQueryKey()],
    [...getGetTripMapQueryKey()],
    [...getListTagsQueryKey()],
  ];
  const all =
    tripId === undefined
      ? keys
      : [
          ...keys,
          [...getGetTripQueryKey(tripId)],
          [...getListTripTagsQueryKey(tripId)],
          [...getListNotesQueryKey(tripId)],
        ];
  return Promise.all(all.map((queryKey) => client.invalidateQueries({ queryKey })));
}

/** After a bulk change: every list and the map once, then each changed trip's detail. */
export function invalidateTrips(client: QueryClient, tripIds: number[]) {
  return Promise.all([
    invalidateTrip(client),
    ...tripIds.map((id) => client.invalidateQueries({ queryKey: getGetTripQueryKey(id) })),
  ]);
}

export function useInvalidateTrip() {
  const client = useQueryClient();
  return useCallback((tripId?: number) => invalidateTrip(client, tripId), [client]);
}
