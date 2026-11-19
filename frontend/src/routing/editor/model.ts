/*
 * The drag-to-reshape editor's line and its edits, without the map (docs/design/routing.md
 * §13.4, D-14, D-93). Pure functions on immutable states, so undo/redo is a stack of states.
 *
 * The edit rules are ported to TypeScript from gpx.studio (https://github.com/gpxstudio/gpx.studio,
 * commit 2e0edc7, 2026-11-15), website/src/lib/components/toolbar/tools/routing/routing-controls.ts:
 * which anchors are the neighbours at a zoom level, what moving or deleting an anchor and
 * appending a point re-route, and how a route answer is spliced between the kept anchors
 * (`routeBetweenAnchors`). Changes: one segment per line, the engine's trackpoint storage is
 * replaced by this immutable state, and each point remembers where it came from (a cached
 * proposal, a saved version, or drawn) so saving can send verifiable pieces (D-93).
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

import {
  type Coord,
  closestPointIndexIn,
  closestSegment,
  computeAnchors,
  distance,
  pt,
} from "./geometry";

/** Where a point of the line came from. Index 0 of `sources` is always "drawn". */
export type Source =
  | { kind: "drawn" }
  | { kind: "proposal"; waypoints: [number, number][]; engine: string; attribution: string }
  | { kind: "version"; routeId: number; engine: string; attribution: string };

export type EditorPoint = {
  readonly lon: number;
  readonly lat: number;
  /** Lowest zoom at which the point is an anchor; null if it isn't one. */
  readonly zoom: number | null;
  /** Index in `sources`, and the point's index in that source's geometry (-1 when drawn). */
  readonly src: number;
  readonly i: number;
};

export type EditorState = {
  readonly points: readonly EditorPoint[];
  readonly sources: readonly Source[];
};

export type Anchor = { index: number; zoom: number; lon: number; lat: number };

/** A route request: the anchors (point indices) it replaces between, and the targets. */
export type RoutePlan = { chain: number[]; targets: Coord[] };

const DRAWN = 0;
/** Clicks closer than this to a point of the line mark that point instead of adding one. */
const SAME_POINT_METERS = 1;

const coord = (p: EditorPoint): Coord => [p.lon, p.lat];

export function coords(state: EditorState): Coord[] {
  return state.points.map(coord);
}

export function emptyState(): EditorState {
  return { points: [], sources: [{ kind: "drawn" }] };
}

/**
 * A state for an existing line (a saved version or a proposal): anchors from its shape
 * (zoom-dependent) plus its control points (always shown, zoom 0).
 */
export function fromLine(line: readonly Coord[], source: Source, controls: Coord[]): EditorState {
  const zooms = new Map(computeAnchors(line).map((a) => [a.index, a.zoom]));
  for (const control of controls) {
    const index = closestPointIndexIn(line, 0, line.length, control);
    if (index !== undefined) zooms.set(index, 0);
  }
  return {
    sources: [{ kind: "drawn" }, source],
    points: line.map(([lon, lat], i) => ({ lon, lat, zoom: zooms.get(i) ?? null, src: 1, i })),
  };
}

/** A straight line through drawn points, every one an anchor (a leg with no route yet). */
export function fromDrawn(points: Coord[]): EditorState {
  return {
    sources: [{ kind: "drawn" }],
    points: points.map(([lon, lat]) => ({ lon, lat, zoom: 0, src: DRAWN, i: -1 })),
  };
}

export function anchors(state: EditorState): Anchor[] {
  const out: Anchor[] = [];
  state.points.forEach((p, index) => {
    if (p.zoom !== null) out.push({ index, zoom: p.zoom, lon: p.lon, lat: p.lat });
  });
  return out;
}

/** The control points saved with the version: the anchors shown at every zoom. */
export function controlPoints(state: EditorState): Coord[] {
  return state.points.filter((p) => p.zoom === 0).map(coord);
}

/** The anchors before and after point `index` that are visible at `zoom`. */
export function neighbours(
  state: EditorState,
  index: number,
  zoom: number,
): [number | null, number | null] {
  let previous: number | null = null;
  let next: number | null = null;
  for (let i = index - 1; i >= 0; i--) {
    const z = pt(state.points, i).zoom;
    if (z !== null && zoom >= z) {
      previous = i;
      break;
    }
  }
  for (let i = index + 1; i < state.points.length; i++) {
    const z = pt(state.points, i).zoom;
    if (z !== null && zoom >= z) {
      next = i;
      break;
    }
  }
  return [previous, next];
}

/** Moving point `index` (an anchor, or a point of the line being dragged) to `to`. */
export function planMove(state: EditorState, index: number, to: Coord, zoom: number): RoutePlan {
  const [previous, next] = neighbours(state, index, zoom);
  const chain: number[] = [];
  const targets: Coord[] = [];
  if (previous !== null) {
    chain.push(previous);
    targets.push(coord(pt(state.points, previous)));
  }
  chain.push(index);
  targets.push(to);
  if (next !== null) {
    chain.push(next);
    targets.push(coord(pt(state.points, next)));
  }
  return { chain, targets };
}

/** A point dragged off the line where it was grabbed: the closest point of the line moves. */
/**
 * A point of the line dragged from where it was grabbed. gpx.studio moves the closest track
 * point; a drawn or sparse line may have none nearby, so the line is first split there.
 * Returns the split line the plan applies to.
 */
export function planDragLine(
  state: EditorState,
  grabbed: Coord,
  to: Coord,
  zoom: number,
): { base: EditorState; plan: RoutePlan } | null {
  const split = splitAt(state, grabbed);
  return split ? { base: split.state, plan: planMove(split.state, split.index, to, zoom) } : null;
}

/** Appending a point after the end of the line. */
export function planAppend(state: EditorState, to: Coord): RoutePlan | null {
  const last = state.points.length - 1;
  if (last < 0) return null;
  return { chain: [last, last], targets: [coord(pt(state.points, last)), to] };
}

/** Deleting an anchor between two others re-routes between them; otherwise no route. */
export function planDelete(state: EditorState, index: number, zoom: number): RoutePlan | null {
  const [previous, next] = neighbours(state, index, zoom);
  if (previous === null || next === null) return null;
  return {
    chain: [previous, next],
    targets: [coord(pt(state.points, previous)), coord(pt(state.points, next))],
  };
}

/** A move without routing (only one point in the line, or no neighbours). */
export function needsRoute(plan: RoutePlan): boolean {
  return plan.chain.length > 1;
}

function withSource(state: EditorState, source: Source): [Source[], number] {
  return [[...state.sources, source], state.sources.length];
}

/** The first point of a line that is drawn alone (a click on an empty editor). */
export function appendFirst(state: EditorState, to: Coord): EditorState {
  return { ...state, points: [{ lon: to[0], lat: to[1], zoom: 0, src: DRAWN, i: -1 }] };
}

/** The only point of the line moves (nothing to route between). */
export function moveAlone(state: EditorState, index: number, to: Coord): EditorState {
  const points = [...state.points];
  points[index] = { lon: to[0], lat: to[1], zoom: 0, src: DRAWN, i: -1 };
  return { ...state, points };
}

/**
 * Replaces what is between the first and the last anchor of `plan.chain` by the route answer
 * `line` (from `source`), as gpx.studio's routeBetweenAnchors does: the anchors at the ends are
 * kept as they are, except if they are the ends of the line, then the route goes in their
 * place. The ends that are not kept and the route points closest to each intermediate target
 * become always-visible anchors.
 */
export function applyRoute(
  state: EditorState,
  plan: RoutePlan,
  line: readonly Coord[],
  source: Source,
): EditorState {
  if (line.length === 0) return state;
  const { chain, targets } = plan;
  const first = pt(chain, 0);
  const last = pt(chain, chain.length - 1);
  const lastIndex = state.points.length - 1;
  const keepFirst =
    first !== 0 && (first !== lastIndex || distance(pt(targets, 0), pt(line, 0)) > 1);
  const keepLast = last !== lastIndex;
  const start = keepFirst ? first + 1 : first;
  const end = keepLast ? last : last + 1;

  const newAnchors = new Set<number>();
  if (!keepFirst) newAnchors.add(0);
  if (!keepLast) newAnchors.add(line.length - 1);
  for (let i = 1; i < chain.length - 1; i++) {
    const closest = closestPointIndexIn(line, 1, line.length - 1, pt(targets, i));
    if (closest !== undefined) newAnchors.add(closest);
  }

  const [sources, src] = withSource(state, source);
  const inserted: EditorPoint[] = line.map(([lon, lat], i) => ({
    lon,
    lat,
    zoom: newAnchors.has(i) ? 0 : null,
    src,
    i,
  }));
  const points = [...state.points.slice(0, start), ...inserted, ...state.points.slice(end)];
  return ensureEnds({ sources, points });
}

/** Deleting an end anchor, or the only point: the points up to the next anchor go too. */
export function deleteWithoutRoute(state: EditorState, index: number, zoom: number): EditorState {
  const [previous, next] = neighbours(state, index, zoom);
  let points: EditorPoint[];
  if (previous === null && next === null) {
    points = state.points.filter((_, i) => i !== index);
  } else if (previous === null && next !== null) {
    points = state.points.slice(next);
  } else if (previous !== null) {
    points = state.points.slice(0, previous + 1);
  } else {
    return state;
  }
  return ensureEnds({ ...state, points });
}

/**
 * A click on the line adds an always-visible anchor there without re-routing: the clicked
 * point of the line if it is within a meter, else a drawn point on the line.
 */
export function insertAnchor(state: EditorState, at: Coord): EditorState {
  return splitAt(state, at)?.state ?? state;
}

/** The line with a fixed anchor at the point closest to `at`, and that anchor's index. */
function splitAt(state: EditorState, at: Coord): { state: EditorState; index: number } | null {
  const line = coords(state);
  const hit = closestSegment(line, at);
  if (!hit) return null;
  const points = [...state.points];
  for (const index of [hit.segment, hit.segment + 1]) {
    if (distance(pt(line, index), hit.at) <= SAME_POINT_METERS) {
      points[index] = { ...pt(points, index), zoom: 0 };
      return { state: { ...state, points }, index };
    }
  }
  const index = hit.segment + 1;
  points.splice(index, 0, { lon: hit.at[0], lat: hit.at[1], zoom: 0, src: DRAWN, i: -1 });
  return { state: { ...state, points }, index };
}

function ensureEnds(state: EditorState): EditorState {
  const points = state.points;
  if (points.length === 0) return state;
  const fixed = [...points];
  const last = fixed.length - 1;
  fixed[0] = { ...(fixed[0] as EditorPoint), zoom: 0 };
  fixed[last] = { ...(fixed[last] as EditorPoint), zoom: 0 };
  return { ...state, points: fixed };
}

/** What the save endpoint takes (`saveEditedRoute` pieces), built from the point sources. */
export type Piece =
  | { source: "proposal"; waypoints: number[][]; start: number; end: number }
  | { source: "version"; route_id: number; start: number; end: number }
  | { source: "drawn"; coordinates: number[][]; engine?: "valhalla" | "ors" | "osrm-fossgis" };

const CLAIMABLE = new Set(["valhalla", "ors", "osrm-fossgis"]);

/**
 * The line as pieces: consecutive points of one source become a slice of it; drawn points are
 * sent as coordinates. Sources in `expired` (proposals the server no longer has) are sent as
 * drawn points that keep their engine's credit. Also returns, per piece, its source index.
 */
export function toPieces(
  state: EditorState,
  expired: ReadonlySet<number> = new Set(),
): { pieces: Piece[]; pieceSources: number[] } {
  const pieces: Piece[] = [];
  const pieceSources: number[] = [];
  for (const p of state.points) {
    const source = state.sources[p.src] as Source;
    const asDrawn = source.kind === "drawn" || expired.has(p.src);
    const previous = pieces[pieces.length - 1];
    const sameSource = pieceSources[pieceSources.length - 1] === p.src;
    if (asDrawn) {
      if (previous?.source === "drawn" && sameSource) {
        previous.coordinates.push([p.lon, p.lat]);
        continue;
      }
      const piece: Piece = { source: "drawn", coordinates: [[p.lon, p.lat]] };
      if (source.kind !== "drawn" && CLAIMABLE.has(source.engine)) {
        piece.engine = source.engine as "valhalla" | "ors" | "osrm-fossgis";
      }
      pieces.push(piece);
    } else {
      if (previous && previous.source !== "drawn" && sameSource && previous.end === p.i - 1) {
        previous.end = p.i;
        continue;
      }
      pieces.push(
        source.kind === "proposal"
          ? { source: "proposal", waypoints: source.waypoints, start: p.i, end: p.i }
          : source.kind === "version"
            ? { source: "version", route_id: source.routeId, start: p.i, end: p.i }
            : { source: "drawn", coordinates: [[p.lon, p.lat]] },
      );
    }
    pieceSources.push(p.src);
  }
  return { pieces, pieceSources };
}

/** The credits for the providers whose routes are in the line, each once. */
export function attributions(state: EditorState): string[] {
  const used = new Set(state.points.map((p) => p.src));
  const out: string[] = [];
  for (const src of used) {
    const source = state.sources[src] as Source;
    if (source.kind !== "drawn" && source.attribution && !out.includes(source.attribution)) {
      out.push(source.attribution);
    }
  }
  return out;
}
