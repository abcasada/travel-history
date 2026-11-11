import type { MapGeoJSONFeature, MapMouseEvent } from "maplibre-gl";
import { useEffect, useMemo, useState } from "react";
import { Layer, Popup, Source, useMap } from "react-map-gl/maplibre";
import { useLocation, useSearchParams } from "react-router";
import { useListImports } from "../api/generated";
import { readFilter, tileQuery } from "../history/filter";

// Tile endpoints (PLAN.md §14). MapLibre fetches tiles in a worker, so the URL must be absolute;
// it is same-origin, so the session cookie goes along.
const POINTS_PATH = "/api/v1/history/tiles/{z}/{x}/{y}.mvt";
const SEGMENTS_PATH = "/api/v1/history/segments/tiles/{z}/{x}/{y}.mvt";
const POINTS_MAX_ZOOM = 16; // beyond this the map over-zooms the z16 tiles
const SEGMENTS_MIN_ZOOM = 5; // the server serves segment tiles from zoom 5

type Picked = { lng: number; lat: number; lines: string[] };

function when(seconds: unknown): string {
  return typeof seconds === "number" ? new Date(seconds * 1000).toLocaleString() : "";
}

function describe(feature: MapGeoJSONFeature): string[] {
  const p = feature.properties ?? {};
  if (feature.layer.id.startsWith("history-segment")) {
    const label = p.kind === "visit" ? `Visit${p.semantic ? ` (${p.semantic})` : ""}` : p.kind;
    return [String(label), `${when(p.t0)} – ${when(p.t1)}`, p.activity ? String(p.activity) : ""];
  }
  if (p.ts !== undefined) return [when(p.ts), `Source: ${p.src}`];
  return [`${Number(p.n).toLocaleString()} points here`, "Zoom in for single points"];
}

/** The signed-in user's raw history on the map: points (grid cells when zoomed out) and an
 * optional Timeline segments overlay, filtered by the date range in the URL. Shown on the
 * History route only. */
export function HistoryLayers() {
  const { pathname } = useLocation();
  if (!pathname.startsWith("/history")) return null;
  return <HistoryLayersInner />;
}

function HistoryLayersInner() {
  const [params] = useSearchParams();
  const filter = readFilter(params);
  const imports = useListImports();
  const revision = useMemo(() => {
    const done = imports.data?.filter((b) => b.status === "done") ?? [];
    return done.length ? `${done.length}.${Math.max(...done.map((b) => b.id))}` : "";
  }, [imports.data]);
  const query = tileQuery(filter, revision);
  const origin = window.location.origin;
  const picked = usePickedFeature();

  return (
    <>
      <Source
        // A new key replaces the source, so a changed filter refetches every tile.
        key={`points${query}`}
        id="history-points"
        type="vector"
        tiles={[`${origin}${POINTS_PATH}${query}`]}
        maxzoom={POINTS_MAX_ZOOM}
      >
        <Layer
          id="history-points"
          type="circle"
          source-layer="points"
          paint={{
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              2,
              ["interpolate", ["linear"], ["ln", ["get", "n"]], 0, 1.5, 9, 5],
              14,
              ["interpolate", ["linear"], ["ln", ["get", "n"]], 0, 3, 9, 8],
            ],
            "circle-color": [
              "interpolate",
              ["linear"],
              ["ln", ["get", "n"]],
              0,
              "#1d4ed8",
              4,
              "#9333ea",
              8,
              "#ea580c",
            ],
            "circle-opacity": 0.75,
          }}
        />
      </Source>
      {filter.segments && (
        <Source
          key={`segments${query}`}
          id="history-segments"
          type="vector"
          tiles={[`${origin}${SEGMENTS_PATH}${query}`]}
          minzoom={SEGMENTS_MIN_ZOOM}
          maxzoom={POINTS_MAX_ZOOM}
        >
          <Layer
            id="history-segment-lines"
            type="line"
            source-layer="segments"
            filter={["==", ["geometry-type"], "LineString"]}
            paint={{
              // Google's activity types; anything else (and raw paths) in slate.
              "line-color": [
                "match",
                ["get", "activity"],
                ["IN_PASSENGER_VEHICLE", "IN_VEHICLE", "MOTORCYCLING"],
                "#2563eb",
                "FLYING",
                "#7c3aed",
                ["IN_TRAIN", "IN_SUBWAY", "IN_TRAM"],
                "#0d9488",
                "IN_BUS",
                "#0891b2",
                ["WALKING", "RUNNING", "HIKING"],
                "#16a34a",
                "CYCLING",
                "#65a30d",
                ["IN_FERRY", "SAILING"],
                "#0284c7",
                "#64748b",
              ],
              "line-width": 2,
              "line-opacity": 0.8,
            }}
          />
          <Layer
            id="history-segment-visits"
            type="circle"
            source-layer="segments"
            filter={["==", ["geometry-type"], "Point"]}
            paint={{
              "circle-radius": 5,
              "circle-color": "#ffffff",
              "circle-stroke-color": "#0f766e",
              "circle-stroke-width": 2,
            }}
          />
        </Source>
      )}
      {picked.value && (
        <Popup
          longitude={picked.value.lng}
          latitude={picked.value.lat}
          onClose={() => picked.clear()}
          closeOnClick={false}
        >
          <div className="text-xs">
            {picked.value.lines.filter(Boolean).map((line) => (
              <div key={line}>{line}</div>
            ))}
          </div>
        </Popup>
      )}
    </>
  );
}

const CLICKABLE = ["history-points", "history-segment-lines", "history-segment-visits"];

/** Click a point, cell or segment to see when it was recorded. One map-level listener that
 * queries whichever history layers exist, so it doesn't matter when they were added. */
function usePickedFeature() {
  const { current: ref } = useMap();
  const [value, setValue] = useState<Picked | null>(null);
  useEffect(() => {
    const map = ref?.getMap();
    if (!map) return;
    const hit = (event: MapMouseEvent) => {
      const layers = CLICKABLE.filter((id) => map.getLayer(id));
      return layers.length ? map.queryRenderedFeatures(event.point, { layers })[0] : undefined;
    };
    const onClick = (event: MapMouseEvent) => {
      const feature = hit(event);
      setValue(
        feature ? { lng: event.lngLat.lng, lat: event.lngLat.lat, lines: describe(feature) } : null,
      );
    };
    const onMove = (event: MapMouseEvent) => {
      map.getCanvas().style.cursor = hit(event) ? "pointer" : "";
    };
    map.on("click", onClick);
    map.on("mousemove", onMove);
    return () => {
      map.off("click", onClick);
      map.off("mousemove", onMove);
      map.getCanvas().style.cursor = "";
    };
  }, [ref]);
  return { value, clear: () => setValue(null) };
}
