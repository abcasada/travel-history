/**
 * Map state shared with the list pane, which lives in another panel (desktop) or below the map
 * (mobile). Only UI state that is neither server data (React Query) nor worth a URL goes here:
 * the current view's bounding box and a pending "pick a point on the map" request.
 */
import { create } from "zustand";

export type LngLat = { lon: number; lat: number };

type Pick = { label: string; onPick: (point: LngLat) => void };

type MapState = {
  /** The visible area as `minLon,minLat,maxLon,maxLat` (the API's bbox format), or null. */
  bbox: string | null;
  setBbox: (bbox: string | null) => void;
  /** While set, the next map click is a point for a form (e.g. a stop's place). */
  pick: Pick | null;
  startPick: (label: string, onPick: (point: LngLat) => void) => void;
  cancelPick: () => void;
  completePick: (point: LngLat) => void;
};

export const useMapStore = create<MapState>((set, get) => ({
  bbox: null,
  setBbox: (bbox) => set({ bbox }),
  pick: null,
  startPick: (label, onPick) => set({ pick: { label, onPick } }),
  cancelPick: () => set({ pick: null }),
  completePick: (point) => {
    const pick = get().pick;
    set({ pick: null });
    pick?.onPick(point);
  },
}));

/** Round to ~11 m so small pans don't change the bbox string (and refetch) needlessly. */
export function toBbox(west: number, south: number, east: number, north: number): string {
  const r = (v: number) => Math.round(v * 1e4) / 1e4;
  const wrap = (lon: number) => ((((lon + 180) % 360) + 360) % 360) - 180;
  // A view wider than the world covers every longitude.
  if (east - west >= 360) return `-180,${r(Math.max(south, -90))},180,${r(Math.min(north, 90))}`;
  return [r(wrap(west)), r(Math.max(south, -90)), r(wrap(east)), r(Math.min(north, 90))].join(",");
}
