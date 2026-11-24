import { SheetLayers } from "../imports/SheetLayers";
import { LegRouteLayer } from "../routing/LegRouteLayer";
import { HistoryLayers } from "./HistoryLayers";
import { MapPickHandler, MapViewTracker } from "./MapPick";
import { TripLayers } from "./TripLayers";

/** Everything drawn on the shared map, for both shells. Each layer decides from the URL whether
 * it shows, so adding a layer means adding it here (frontend-patterns.md, "Map layers"). */
export function MapLayers() {
  return (
    <>
      <HistoryLayers />
      <TripLayers />
      <LegRouteLayer />
      <SheetLayers />
      <MapPickHandler />
      <MapViewTracker />
    </>
  );
}
