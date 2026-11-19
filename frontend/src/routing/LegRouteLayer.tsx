import type { FeatureCollection, LineString, MultiLineString, Point } from "geojson";
import { lazy, Suspense, useMemo } from "react";
import { Layer, Source } from "react-map-gl/maplibre";
import { useLocation } from "react-router";
import { useGetLeg, useGetRoute } from "../api/generated";
import { selectedLegId } from "../trips/paths";
import { useRoutingStore } from "./store";

const RouteEditorLayer = lazy(() => import("./editor/RouteEditorLayer"));

/**
 * Map side of a leg's route view (`/trips/:tripId/legs/:legId/route`): draws the leg's current
 * route version, if it has one, and a proposal not yet saved (item 25). While the drag editor
 * (item 26, desktop only) is open for this leg, its own layer draws the line being reshaped and
 * its anchors instead; the list pane's LegRoutePage holds its toolbar. Saving creates a new
 * frozen version (rule 5); nothing here re-routes a saved one.
 */
export function LegRouteLayer() {
  const { pathname } = useLocation();
  const legId = selectedLegId(pathname);
  const editing = useRoutingStore((s) => s.editingLegId);
  if (legId === null) return null;
  if (editing === legId) {
    return (
      <Suspense fallback={null}>
        <RouteEditorLayer />
      </Suspense>
    );
  }
  return (
    <>
      <CurrentRoute legId={legId} />
      <Proposal legId={legId} />
    </>
  );
}

function Proposal({ legId }: { legId: number }) {
  const { legId: shown, proposal, waypoints } = useRoutingStore();
  const data = useMemo(() => {
    const route = proposal?.routes[0];
    if (shown !== legId || !route) return null;
    const line: FeatureCollection<LineString | Point> = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { role: "line" },
          geometry: route.geometry as LineString,
        },
        ...waypoints.map((p) => ({
          type: "Feature" as const,
          properties: { role: "waypoint" },
          geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
        })),
      ],
    };
    return line;
  }, [shown, legId, proposal, waypoints]);
  if (!data) return null;
  return (
    <Source id="leg-proposal" type="geojson" data={data}>
      <Layer
        id="leg-proposal-line"
        type="line"
        filter={["==", ["get", "role"], "line"]}
        layout={{ "line-cap": "round", "line-join": "round" }}
        paint={{ "line-color": "#2563eb", "line-width": 5, "line-opacity": 0.85 }}
      />
      <Layer
        id="leg-proposal-waypoints"
        type="circle"
        filter={["==", ["get", "role"], "waypoint"]}
        paint={{
          "circle-radius": 6,
          "circle-color": "#ffffff",
          "circle-stroke-color": "#2563eb",
          "circle-stroke-width": 3,
        }}
      />
    </Source>
  );
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
