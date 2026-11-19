/*
 * Anchor geometry for the drag-to-reshape editor (docs/design/routing.md §13.4, D-14).
 *
 * Ported to TypeScript from gpx.studio (https://github.com/gpxstudio/gpx.studio, commit
 * 2e0edc7, 2026-11-15): gpx-rs/src/core/algorithm/anchors.rs and simplify.rs
 * (Ramer-Douglas-Peucker with selection distances, anchor zoom levels), gpx-rs/src/core/utils.rs
 * (planar cross-track distance) and website/src/lib/geo/closest-point.ts. Changes: points are
 * [lon, lat] arrays, one segment per line, and an extra helper projects a point onto the line.
 *
 * MIT License
 *
 * Copyright (c) 2026 gpx.studio
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

export type Coord = readonly [number, number]; // [lon, lat]

/** `items[index]` for an index the caller knows is in range (noUncheckedIndexedAccess). */
export function pt<T>(items: readonly T[], index: number): T {
  return items[index] as T;
}

/** Highest zoom level of the map at which an anchor can appear. */
export const MAX_ANCHOR_ZOOM = 22;
/** Details smaller than this (in meters) do not get an anchor. */
const ANCHOR_EPSILON = 1;
const EARTH_RADIUS_METERS = 6371008.8;
const METERS_PER_LATITUDE_DEGREE = 111320;
const TO_RADIANS = Math.PI / 180;

/** Haversine distance in meters. */
export function distance(a: Coord, b: Coord): number {
  const lat1 = a[1] * TO_RADIANS;
  const lat2 = b[1] * TO_RADIANS;
  const dLat = lat2 - lat1;
  const dLng = (b[0] - a[0]) * TO_RADIANS;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.sqrt(Math.min(1, h)));
}

/**
 * Position, between 0 (at `(x1, y1)`) and 1 (at `(x2, y2)`), of the point of the segment that is
 * the closest to `(x3, y3)`. A degenerate segment (same ends) is a point.
 */
function closestOnSegment(x1: number, y1: number, x2: number, y2: number, x3: number, y3: number) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return 0;
  return Math.max(0, Math.min(1, ((x3 - x1) * dx + (y3 - y1) * dy) / lengthSquared));
}

/** Approximate planar projection, in meters, around the latitude of `origin`. */
function planar(origin: Coord) {
  const kx = Math.cos(origin[1] * TO_RADIANS) * METERS_PER_LATITUDE_DEGREE;
  return {
    toMeters: (p: Coord): [number, number] => [p[0] * kx, p[1] * METERS_PER_LATITUDE_DEGREE],
    toDegrees: (x: number, y: number): [number, number] => [x / kx, y / METERS_PER_LATITUDE_DEGREE],
  };
}

/**
 * The distance in meters between the segment p1-p2 and the point p3 (planar geometry, ignores
 * the curvature of the earth).
 */
export function crossarc(p1: Coord, p2: Coord, p3: Coord): number {
  const plane = planar(p1);
  const [x1, y1] = plane.toMeters(p1);
  const [x2, y2] = plane.toMeters(p2);
  const [x3, y3] = plane.toMeters(p3);
  const t = closestOnSegment(x1, y1, x2, y2, x3, y3);
  return Math.hypot(x3 - (x1 + t * (x2 - x1)), y3 - (y1 + t * (y2 - y1)));
}

/** The point of the segment p1-p2 that is the closest to p3. */
export function projected(p1: Coord, p2: Coord, p3: Coord): [number, number] {
  const plane = planar(p1);
  const [x1, y1] = plane.toMeters(p1);
  const [x2, y2] = plane.toMeters(p2);
  const [x3, y3] = plane.toMeters(p3);
  const t = closestOnSegment(x1, y1, x2, y2, x3, y3);
  return plane.toDegrees(x1 + t * (x2 - x1), y1 + t * (y2 - y1));
}

/**
 * Ramer-Douglas-Peucker on a line with the cross-track distance in meters. Gives the kept
 * indices in order, each with the distance at which it was selected (`null` for the ends, which
 * are always kept). Iterative: a long line would overflow the stack with recursion.
 */
export function ramerDouglasPeucker(
  points: readonly Coord[],
  epsilon: number,
): { index: number; distance: number | null }[] {
  if (points.length === 0) return [];
  if (points.length === 1) return [{ index: 0, distance: null }];
  const last = points.length - 1;
  const kept: { index: number; distance: number | null }[] = [{ index: 0, distance: null }];
  type Step = { range: [number, number] } | { keep: number; distance: number };
  const steps: Step[] = [{ range: [0, last] }];
  while (steps.length > 0) {
    const step = steps.pop() as Step;
    if ("keep" in step) {
      kept.push({ index: step.keep, distance: step.distance });
      continue;
    }
    const [start, end] = step.range;
    let maxIndex = -1;
    let maxDistance = 0;
    for (let i = start + 1; i < end; i++) {
      const d = crossarc(pt(points, start), pt(points, end), pt(points, i));
      if (d > maxDistance) {
        maxIndex = i;
        maxDistance = d;
      }
    }
    if (maxIndex >= 0 && maxDistance > epsilon) {
      // the last one pushed is done first
      steps.push({ range: [maxIndex, end] });
      steps.push({ keep: maxIndex, distance: maxDistance });
      steps.push({ range: [start, maxIndex] });
    }
  }
  kept.push({ index: last, distance: null });
  return kept;
}

/**
 * Lowest map zoom level at which an anchor selected at `distance` meters from the line of its
 * neighbours is worth showing: the smaller the detail, the higher the zoom. The ends of a line
 * (no distance) are always shown.
 */
export function anchorZoom(lat: number, distance: number | null): number {
  if (distance === null) return 0;
  const width = (EARTH_RADIUS_METERS * Math.cos(lat * TO_RADIANS)) / distance;
  const zoom = Math.round(Math.log2(width));
  if (Number.isNaN(zoom)) return 0;
  return Math.max(0, Math.min(MAX_ANCHOR_ZOOM, zoom));
}

/**
 * The anchors of a line, as `{index, zoom}` sorted by index: the points kept by the
 * Ramer-Douglas-Peucker simplification of its path, the ones for smaller details being shown at
 * higher zoom levels only.
 */
export function computeAnchors(points: readonly Coord[]): { index: number; zoom: number }[] {
  return ramerDouglasPeucker(points, ANCHOR_EPSILON).map(({ index, distance }) => ({
    index,
    zoom: anchorZoom(pt(points, index)[1], distance),
  }));
}

/**
 * Index of the point, among the points `from` (included) to `to` (excluded) of a line, that is
 * the closest to `point`: one of the two ends of the segment of the line that passes the closest
 * to it. `undefined` for an empty range. Planar approximation.
 */
export function closestPointIndexIn(
  points: readonly Coord[],
  from: number,
  to: number,
  point: Coord,
): number | undefined {
  const count = Math.max(0, to - from);
  if (count === 0) return undefined;
  if (count === 1) return from;
  const kx = Math.cos(point[1] * TO_RADIANS) * METERS_PER_LATITUDE_DEGREE;
  const ky = METERS_PER_LATITUDE_DEGREE;
  const x = (i: number) => (pt(points, from + i)[0] - point[0]) * kx;
  const y = (i: number) => (pt(points, from + i)[1] - point[1]) * ky;
  let best = 0;
  let bestDistance = Number.MAX_VALUE;
  for (let i = 0; i < count - 1; i++) {
    const [ax, ay, bx, by] = [x(i), y(i), x(i + 1), y(i + 1)];
    const [dx, dy] = [bx - ax, by - ay];
    const length = dx * dx + dy * dy;
    // the point is at the origin: the closest position on the segment, as a ratio
    const t = length === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / length));
    const d = Math.hypot(ax + t * dx, ay + t * dy);
    if (d < bestDistance) {
      bestDistance = d;
      best = t < 0.5 ? i : i + 1;
    }
  }
  return from + best;
}

/**
 * Where `point` falls on the line: the index of the segment (between points `segment` and
 * `segment + 1`) that passes the closest, and the closest position on it.
 */
export function closestSegment(
  points: readonly Coord[],
  point: Coord,
): { segment: number; at: [number, number] } | undefined {
  if (points.length < 2) return undefined;
  let best = 0;
  let bestDistance = Number.MAX_VALUE;
  for (let i = 0; i < points.length - 1; i++) {
    const d = crossarc(pt(points, i), pt(points, i + 1), point);
    if (d < bestDistance) {
      bestDistance = d;
      best = i;
    }
  }
  return { segment: best, at: projected(pt(points, best), pt(points, best + 1), point) };
}
