import { keepPreviousData } from "@tanstack/react-query";
import type { ExpressionSpecification, MapMouseEvent } from "maplibre-gl";
import { useEffect, useMemo } from "react";
import { Layer, Source, useMap } from "react-map-gl/maplibre";
import { useShallow } from "zustand/react/shallow";
import { useLocation, useNavigate, useSearchParams } from "react-router";
import { useGetTripMap } from "../api/generated";
import { useRoutingStore } from "../routing/store";
import { apiParams, readTripFilter } from "../trips/filter";
import { MODE_COLORS } from "../trips/labels";
import { paths, selectedTripId, showsTrips } from "../trips/paths";
import { highlighted, useSelectionStore } from "../trips/selection";
import { legFeatures, stopFeatures, tripBounds } from "./geo";
import { useMapStore } from "./store";

const MODE_COLOR: ExpressionSpecification = [
  "match",
  ["get", "mode"],
  ...Object.entries(MODE_COLORS).flat(),
  MODE_COLORS.other,
] as unknown as ExpressionSpecification;

const CLICKABLE = ["trip-legs", "trip-stops"];

/**
 * The trips on the map home and on trip pages (PLAN.md §18.2): every leg as a line coloured by
 * mode and every stop as a dot, from `GET /trips/map` with the list's filters (the map ignores
 * "only in view", which would hide what you pan to). On a trip's pages all trips are drawn, the
 * trip itself highlighted and fitted. Click a line or dot to open its trip.
 *
 * Routed legs (items 25-26) need no change here while they come through `/trips/map`; when trip
 * vector tiles from `route_simplified` arrive, they replace the `trip-legs` source (see
 * docs/design/frontend-patterns.md, "Map layers").
 */
export function TripLayers() {
  const { pathname } = useLocation();
  if (!showsTrips(pathname)) return null;
  return <TripLayersInner />;
}

function TripLayersInner() {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const selected = selectedTripId(pathname);
  // On a trip page the list's filter isn't in the URL any more: draw every trip.
  const query = useGetTripMap(
    selected === null ? apiParams({ ...readTripFilter(params), inView: false }) : {},
    { query: { placeholderData: keepPreviousData } },
  );
  const legs = useMemo(() => legFeatures(query.data?.legs ?? []), [query.data]);
  const stops = useMemo(() => stopFeatures(query.data?.stops ?? []), [query.data]);
  useFitTrip(selected, query.data);
  useFitSelection(selected === null ? query.data : undefined);
  useTripClicks();
  // On the list, the trips under the cursor and in the selection stand out (ui.md §18.4).
  const listed = useSelectionStore(useShallow(highlighted));

  const isSelected: ExpressionSpecification =
    selected !== null
      ? ["==", ["get", "trip_id"], selected]
      : ["in", ["get", "trip_id"], ["literal", listed]];
  const dimOthers = selected !== null || listed.length > 0;
  return (
    <>
      <Source id="trip-legs" type="geojson" data={legs}>
        <Layer
          id="trip-legs"
          type="line"
          layout={{ "line-cap": "round", "line-join": "round" }}
          paint={{
            "line-color": MODE_COLOR,
            "line-width": ["case", isSelected, 4, 2.5],
            "line-opacity": dimOthers ? ["case", isSelected, 0.95, 0.3] : 0.85,
            // Straight placeholder lines are dashed until the leg has a route (items 25-26).
            "line-dasharray": ["case", ["get", "routed"], ["literal", [1]], ["literal", [2, 1.5]]],
          }}
        />
      </Source>
      <Source id="trip-stops" type="geojson" data={stops}>
        <Layer
          id="trip-stops"
          type="circle"
          paint={{
            "circle-radius": ["case", isSelected, 6, 4],
            "circle-color": "#ffffff",
            "circle-stroke-color": "#1e3a8a",
            "circle-stroke-width": 2,
            "circle-opacity": dimOthers ? ["case", isSelected, 1, 0.4] : 1,
            "circle-stroke-opacity": dimOthers ? ["case", isSelected, 1, 0.4] : 1,
          }}
        />
        <Layer
          id="trip-stop-labels"
          type="symbol"
          filter={isSelected}
          layout={{
            "text-field": ["get", "name"],
            // A font the basemap's glyph server has (MapLibre's default isn't served there).
            "text-font": ["Noto Sans Regular"],
            "text-size": 12,
            "text-offset": [0, 1.1],
            "text-anchor": "top",
            "text-optional": true,
          }}
          paint={{ "text-color": "#1e293b", "text-halo-color": "#ffffff", "text-halo-width": 1.5 }}
        />
      </Source>
    </>
  );
}

/** Fit the map to the selected trip once its geometry is known (again when the trip changes). */
function useFitTrip(selected: number | null, data: Parameters<typeof tripBounds>[0] | undefined) {
  const { current: ref } = useMap();
  const bounds = useMemo(
    () => (selected !== null && data ? tripBounds(data, selected) : null),
    [selected, data],
  );
  const key = bounds ? `${selected}:${bounds.flat().join(",")}` : null;
  // biome-ignore lint/correctness/useExhaustiveDependencies: refit only when the key changes
  useEffect(() => {
    const map = ref?.getMap();
    if (!map || !bounds) return;
    map.fitBounds(bounds, { padding: 60, maxZoom: 12, duration: 600 });
  }, [key, ref]);
}

/** `f` on the list: fit the map to the selected trips (or the cursor's trip). */
function useFitSelection(data: Parameters<typeof tripBounds>[0] | undefined) {
  const { current: ref } = useMap();
  const fitRequest = useSelectionStore((s) => s.fitRequest);
  // biome-ignore lint/correctness/useExhaustiveDependencies: fit only when `f` is pressed
  useEffect(() => {
    const map = ref?.getMap();
    if (!fitRequest || !map || !data) return;
    const bounds = tripBounds(data, highlighted(useSelectionStore.getState()));
    if (bounds) map.fitBounds(bounds, { padding: 60, maxZoom: 12, duration: 600 });
  }, [fitRequest, ref]);
}

/** A pending map pick (a form asking for a point) or the route editor takes the clicks. */
function mapIsBusy(): boolean {
  return useMapStore.getState().pick !== null || useRoutingStore.getState().editingLegId !== null;
}

/** Click a trip's line or stop to open it; pointer cursor over them. A pending map pick (a
 * form asking for a point) takes the click instead. */
function useTripClicks() {
  const { current: ref } = useMap();
  const navigate = useNavigate();
  useEffect(() => {
    const map = ref?.getMap();
    if (!map) return;
    const hit = (event: MapMouseEvent) => {
      const layers = CLICKABLE.filter((id) => map.getLayer(id));
      return layers.length ? map.queryRenderedFeatures(event.point, { layers })[0] : undefined;
    };
    const onClick = (event: MapMouseEvent) => {
      if (mapIsBusy()) return;
      const tripId = Number(hit(event)?.properties?.trip_id);
      if (Number.isInteger(tripId) && tripId > 0) navigate(paths.trip(tripId));
    };
    const onMove = (event: MapMouseEvent) => {
      if (mapIsBusy()) return;
      map.getCanvas().style.cursor = hit(event) ? "pointer" : "";
    };
    map.on("click", onClick);
    map.on("mousemove", onMove);
    return () => {
      map.off("click", onClick);
      map.off("mousemove", onMove);
    };
  }, [ref, navigate]);
}
