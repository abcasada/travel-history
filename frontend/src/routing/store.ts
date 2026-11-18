/**
 * The route proposal being looked at, shared between the list pane (LegRoutePage, which asks
 * for it and saves it) and the map (LegRouteLayer, which draws it). A proposal is not saved
 * data: it lives here until it is saved as a version or the user leaves the leg.
 */
import { create } from "zustand";
import type { RouteProposalOut } from "../api/generated";
import type { LngLat } from "../map/store";

type RoutingState = {
  legId: number | null;
  /** Control points in order: start, vias, end. */
  waypoints: LngLat[];
  proposal: RouteProposalOut | null;
  show: (legId: number, waypoints: LngLat[], proposal: RouteProposalOut) => void;
  clear: () => void;
};

export const useRoutingStore = create<RoutingState>((set) => ({
  legId: null,
  waypoints: [],
  proposal: null,
  show: (legId, waypoints, proposal) => set({ legId, waypoints, proposal }),
  clear: () => set({ legId: null, waypoints: [], proposal: null }),
}));

/** "2 h 05 min" / "35 min" from seconds. */
export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`;
}

export const ENGINE_LABELS: Record<string, string> = {
  valhalla: "Valhalla (self-hosted)",
  ors: "openrouteservice",
  "osrm-fossgis": "FOSSGIS OSRM (emergency fallback)",
};

/** The FOSSGIS service asks that wrong routes be fixed in OpenStreetMap. */
export const FIX_THE_MAP_URL = "https://www.openstreetmap.org/fixthemap";
