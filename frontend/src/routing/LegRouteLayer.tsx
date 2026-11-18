import type { MultiLineString } from "geojson";
import { Layer, Source } from "react-map-gl/maplibre";
import { useLocation } from "react-router";
import { useGetLeg, useGetRoute } from "../api/generated";
import { selectedLegId } from "../trips/paths";

/**
 * Map side of a leg's route view (`/trips/:tripId/legs/:legId/route`): draws the leg's current
 * route version, if it has one. This is the slot the drag-to-reshape editor (item 26) replaces:
 * it renders its anchors and the live route here, and the list pane's LegRoutePage holds its
 * controls. Saving creates a new frozen version (rule 5); nothing here re-routes.
 */
export function LegRouteLayer() {
  const { pathname } = useLocation();
  const legId = selectedLegId(pathname);
  if (legId === null) return null;
  return <CurrentRoute legId={legId} />;
}

function CurrentRoute({ legId }: { legId: number }) {
  const leg = useGetLeg(legId);
  const routeId = leg.data?.current_route_id ?? null;
  const route = useGetRoute(routeId ?? 0, { query: { enabled: routeId !== null } });
  if (!route.data) return null;
  return (
    <Source id="leg-route" type="geojson" data={route.data.geometry as unknown as MultiLineString}>
      <Layer
        id="leg-route"
        type="line"
        layout={{ "line-cap": "round", "line-join": "round" }}
        paint={{ "line-color": "#dc2626", "line-width": 5, "line-opacity": 0.9 }}
      />
    </Source>
  );
}
