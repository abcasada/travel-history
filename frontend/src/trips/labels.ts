/** Display labels for the API's enum values (one place, so every page says the same). */
import type { StopKind, TravelMode, Visibility } from "../api/generated";

export const MODE_LABELS: Record<TravelMode, string> = {
  drive: "Drive",
  flight: "Flight",
  train: "Train",
  bus: "Bus",
  boat: "Boat",
  walk: "Walk",
  other: "Other",
};

/** Line colours on the map, by mode (also used as legend swatches). */
export const MODE_COLORS: Record<TravelMode, string> = {
  drive: "#2563eb",
  flight: "#7c3aed",
  train: "#0d9488",
  bus: "#0891b2",
  boat: "#0284c7",
  walk: "#16a34a",
  other: "#64748b",
};

export const STOP_KIND_LABELS: Record<StopKind, string> = {
  destination: "Destination",
  lodging: "Lodging",
  visit: "Visit",
  waypoint: "Waypoint",
};

export const VISIBILITY_LABELS: Record<Visibility, string> = {
  private: "Private (only me)",
  participants: "Participants",
  family: "Family",
  public: "Public",
};

export const MODES = Object.keys(MODE_LABELS) as TravelMode[];
export const STOP_KINDS = Object.keys(STOP_KIND_LABELS) as StopKind[];
// Public trips need sharing settings and the public renderer (phase 8); not offered yet.
export const EDITABLE_VISIBILITIES: Visibility[] = ["private", "participants", "family"];

export function label<K extends string>(labels: Record<K, string>, value: string): string {
  return (labels as Record<string, string>)[value] ?? value;
}
