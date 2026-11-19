import type { Coord } from "./geometry";
import {
  anchors,
  applyRoute,
  attributions,
  controlPoints,
  coords,
  deleteWithoutRoute,
  fromDrawn,
  fromLine,
  insertAnchor,
  neighbours,
  planAppend,
  planDelete,
  planDragLine,
  planMove,
  type Source,
  toPieces,
} from "./model";

// Synthetic line: east along lat 38 with a corner going north at its middle.
const LINE: Coord[] = [
  [-97.5, 38.0],
  [-97.49, 38.0],
  [-97.48, 38.0],
  [-97.48, 38.01],
  [-97.48, 38.02],
  [-97.47, 38.02],
  [-97.46, 38.02],
];
const VERSION: Source = { kind: "version", routeId: 7, engine: "valhalla", attribution: "V" };
const ORS = "© openrouteservice by HeiGIT, data © OpenStreetMap";
const proposal = (waypoints: Coord[], engine = "valhalla"): Source => ({
  kind: "proposal",
  waypoints: waypoints.map(([x, y]) => [x, y]),
  engine,
  attribution: engine === "ors" ? ORS : "V",
});

const ENDS: Coord[] = [LINE[0] as Coord, LINE[6] as Coord];
// Every corner fixed (zoom 0), as after loading a version with these control points.
const base = () => fromLine(LINE, VERSION, [...ENDS, LINE[2] as Coord, LINE[4] as Coord]);

test("a loaded line gets its corners as zoom-dependent anchors, its control points fixed", () => {
  const state = fromLine(LINE, VERSION, ENDS);
  const found = anchors(state);
  expect(found.map((a) => a.index)).toEqual([0, 2, 4, 6]);
  // ~1 km corners show from about zoom 12; the ends always
  expect(found.map((a) => a.zoom > 0)).toEqual([false, true, true, false]);
  expect(controlPoints(state)).toEqual(ENDS);
  expect(controlPoints(base())).toEqual([LINE[0], LINE[2], LINE[4], LINE[6]]);
});

test("neighbours are the anchors visible at the zoom", () => {
  const state = base();
  const zoomed = {
    ...state,
    points: state.points.map((p, i) => (i === 2 ? { ...p, zoom: 15 } : p)),
  };
  expect(neighbours(zoomed, 3, 16)).toEqual([2, 4]);
  expect(neighbours(zoomed, 3, 10)).toEqual([0, 4]);
});

test("moving an anchor routes from the previous to the next anchor through the new place", () => {
  const state = base();
  const plan = planMove(state, 4, [-97.47, 38.03], 12);
  expect(plan).toEqual({ chain: [2, 4, 6], targets: [LINE[2], [-97.47, 38.03], LINE[6]] });
  const route: Coord[] = [
    [-97.4801, 38.0001],
    [-97.475, 38.025],
    [-97.47, 38.03],
    [-97.46, 38.0201],
  ];
  const next = applyRoute(state, plan, route, proposal(plan.targets));
  // The previous anchor is kept; the end of the line is replaced by the route's end.
  expect(coords(next)).toEqual([LINE[0], LINE[1], LINE[2], ...route]);
  // The point of the route closest to the dragged place becomes a fixed anchor, and so does
  // the new end.
  expect(next.points.map((p) => p.zoom)).toEqual([0, null, 0, null, null, 0, 0]);
  expect(next.sources).toHaveLength(3);
  expect(state.points).toHaveLength(7); // the old state is untouched (undo)
});

test("moving the start replaces it with the route's start", () => {
  const state = base();
  const plan = planMove(state, 0, [-97.51, 37.99], 12);
  expect(plan.chain).toEqual([0, 2]);
  const route: Coord[] = [
    [-97.51, 37.99],
    [-97.49, 38.0],
    [-97.48, 38.0001],
  ];
  const next = applyRoute(state, plan, route, proposal(plan.targets));
  expect(coords(next).slice(0, 4)).toEqual([...route, LINE[2]]);
  expect(next.points[0]?.zoom).toBe(0);
});

test("dragging the line moves its point there, splitting it if it has none", () => {
  const state = base();
  const onPoint = planDragLine(state, [-97.48, 38.0100000001], [-97.47, 38.01], 12);
  expect(onPoint?.plan.chain).toEqual([2, 3, 4]);
  expect(onPoint?.base.points).toHaveLength(7);
  const straight = fromDrawn([LINE[0] as Coord, LINE[2] as Coord]);
  const split = planDragLine(straight, [-97.49, 38.001], [-97.49, 38.01], 12);
  expect(split?.plan.chain).toEqual([0, 1, 2]);
  expect(split?.plan.targets).toEqual([LINE[0], [-97.49, 38.01], LINE[2]]);
  expect(split && coords(split.base)[1]?.[0]).toBeCloseTo(-97.49, 6);
});

test("appending routes from the end to the new point", () => {
  const state = base();
  const plan = planAppend(state, [-97.4, 38.1]);
  expect(plan).toEqual({ chain: [6, 6], targets: [LINE[6], [-97.4, 38.1]] });
  if (!plan) throw new Error("no plan");
  const route: Coord[] = [
    [-97.46, 38.0201],
    [-97.43, 38.05],
    [-97.4, 38.1],
  ];
  const next = applyRoute(state, plan, route, proposal(plan.targets));
  expect(coords(next)).toEqual([...LINE, ...route]);
  expect(next.points[6]?.zoom).toBe(0);
  expect(next.points[9]?.zoom).toBe(0);
});

test("deleting a middle anchor re-routes its neighbours; an end anchor just goes", () => {
  const state = base();
  expect(planDelete(state, 2, 12)).toEqual({ chain: [0, 4], targets: [LINE[0], LINE[4]] });
  expect(planDelete(state, 0, 12)).toBeNull();
  const shorter = deleteWithoutRoute(state, 0, 12);
  expect(coords(shorter)).toEqual(LINE.slice(2));
  expect(shorter.points[0]?.zoom).toBe(0);
  const end = deleteWithoutRoute(state, 6, 12);
  expect(coords(end)).toEqual(LINE.slice(0, 5));
  const lone = deleteWithoutRoute(fromDrawn([[-97, 38]]), 0, 12);
  expect(lone.points).toEqual([]);
});

test("clicking the line adds a fixed anchor without routing", () => {
  const state = fromLine(LINE, VERSION, []);
  const onVertex = insertAnchor(state, [-97.49, 38.0000001]);
  expect(coords(onVertex)).toEqual(LINE);
  expect(onVertex.points[1]?.zoom).toBe(0);
  const between = insertAnchor(state, [-97.495, 38.001]);
  expect(between.points).toHaveLength(8);
  expect(between.points[1]).toMatchObject({ zoom: 0, src: 0, i: -1 });
  expect(between.points[1]?.lat).toBeCloseTo(38, 6);
});

test("the line is saved as slices of its sources and drawn points", () => {
  const state = base();
  const plan = planMove(state, 4, [-97.47, 38.03], 12);
  const routeLine: Coord[] = [
    [-97.4801, 38.0001],
    [-97.47, 38.03],
    [-97.46, 38.0201],
  ];
  const routed = applyRoute(state, plan, routeLine, proposal(plan.targets, "ors"));
  const edited = insertAnchor(routed, [-97.495, 38.001]); // a drawn point on the first segment
  const { pieces, pieceSources } = toPieces(edited);
  expect(pieces).toEqual([
    { source: "version", route_id: 7, start: 0, end: 0 },
    { source: "drawn", coordinates: [[expect.any(Number), expect.any(Number)]] },
    { source: "version", route_id: 7, start: 1, end: 2 },
    { source: "proposal", waypoints: [LINE[2], [-97.47, 38.03], LINE[6]], start: 0, end: 2 },
  ]);
  expect(pieceSources).toEqual([1, 0, 1, 2]);
  // An expired proposal is resent as drawn points that keep the provider's credit.
  const resent = toPieces(edited, new Set([2])).pieces;
  expect(resent[3]).toEqual({ source: "drawn", coordinates: routeLine, engine: "ors" });
  expect(attributions(edited)).toEqual(["V", ORS]);
});
