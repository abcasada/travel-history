/**
 * Turns the trip map payload (`GET /trips/map`) into GeoJSON for MapLibre. Legs are straight
 * lines between their end points until they have routes; flights are drawn as great-circle arcs
 * (PLAN.md §12). Routed legs (items 25-26) arrive with `routed: true` and their own coordinates,
 * which are used as they are.
 */
import type { FeatureCollection, LineString, Point, Position } from "geojson";
import type { MapLegOut, MapStopOut, TripMapOut } from "../api/generated";

export type LegProps = { trip_id: number; leg_id: number; mode: string; routed: boolean };
export type StopProps = { trip_id: number; stop_id: number; kind: string; name: string };

const RAD = Math.PI / 180;

/** Points along the great circle from a to b (lon/lat degrees). Longitudes are unwrapped so an
 * arc across the antimeridian stays continuous (MapLibre draws it across the world copies). */
export function greatCircle(a: Position, b: Position, steps = 32): Position[] {
  const [lon1, lat1] = [(a[0] ?? 0) * RAD, (a[1] ?? 0) * RAD];
  const [lon2, lat2] = [(b[0] ?? 0) * RAD, (b[1] ?? 0) * RAD];
  const d =
    2 *
    Math.asin(
      Math.sqrt(
        Math.sin((lat2 - lat1) / 2) ** 2 +
          Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2,
      ),
    );
  if (d < 1e-9) return [a, b];
  const out: Position[] = [];
  let previous: number | null = null;
  for (let i = 0; i <= steps; i++) {
    const f = i / steps;
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);
    let lon = Math.atan2(y, x) / RAD;
    const lat = Math.atan2(z, Math.sqrt(x * x + y * y)) / RAD;
    if (previous !== null) {
      while (lon - previous > 180) lon -= 360;
      while (lon - previous < -180) lon += 360;
    }
    previous = lon;
    out.push([lon, lat]);
  }
  return out;
}

export function legLine(leg: MapLegOut): Position[] {
  const coords = leg.coordinates as Position[];
  const [start, end] = coords;
  if (!leg.routed && leg.mode === "flight" && coords.length === 2 && start && end) {
    return greatCircle(start, end);
  }
  return coords;
}

export function legFeatures(legs: MapLegOut[]): FeatureCollection<LineString, LegProps> {
  return {
    type: "FeatureCollection",
    features: legs.map((leg) => ({
      type: "Feature",
      id: leg.id,
      geometry: { type: "LineString", coordinates: legLine(leg) },
      properties: { trip_id: leg.trip_id, leg_id: leg.id, mode: leg.mode, routed: leg.routed },
    })),
  };
}

export function stopFeatures(stops: MapStopOut[]): FeatureCollection<Point, StopProps> {
  return {
    type: "FeatureCollection",
    features: stops.map((stop) => ({
      type: "Feature",
      id: stop.id,
      geometry: { type: "Point", coordinates: [stop.lon, stop.lat] },
      properties: { trip_id: stop.trip_id, stop_id: stop.id, kind: stop.kind, name: stop.name },
    })),
  };
}

export type Bounds = [[number, number], [number, number]];

/** Bounding box of one trip's stops and legs, or null if it has nothing to draw. */
export function tripBounds(data: TripMapOut, tripId: number): Bounds | null {
  const points: Position[] = [
    ...data.stops.filter((s) => s.trip_id === tripId).map((s) => [s.lon, s.lat]),
    ...data.legs.filter((g) => g.trip_id === tripId).flatMap(legLine),
  ];
  if (!points.length) return null;
  const lons = points.map((p) => p[0] ?? 0);
  const lats = points.map((p) => p[1] ?? 0);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}
