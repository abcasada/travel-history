/**
 * After a change to a trip (or anything on it), refresh exactly what can show it: its detail,
 * every trip list page and the trip map, whatever their filters. Mutations call this in their
 * onSuccess; nothing else touches the trips' cached queries (frontend-patterns.md, "Data").
 */
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { getGetTripMapQueryKey, getGetTripQueryKey, getListTripsQueryKey } from "../api/generated";

export function invalidateTrip(client: QueryClient, tripId?: number) {
  const keys: readonly unknown[][] = [[...getListTripsQueryKey()], [...getGetTripMapQueryKey()]];
  const all = tripId === undefined ? keys : [...keys, [...getGetTripQueryKey(tripId)]];
  return Promise.all(all.map((queryKey) => client.invalidateQueries({ queryKey })));
}

export function useInvalidateTrip() {
  const client = useQueryClient();
  return useCallback((tripId?: number) => invalidateTrip(client, tripId), [client]);
}
