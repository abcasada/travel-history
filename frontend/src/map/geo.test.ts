import type { MapLegOut } from "../api/generated";
import { greatCircle, legFeatures, tripBounds } from "./geo";
import { toBbox, useMapStore } from "./store";

const leg = (over: Partial<MapLegOut>): MapLegOut => ({
  id: 1,
  trip_id: 10,
  sequence: 1,
  mode: "drive",
  coordinates: [
    [-97, 38],
    [-96, 39],
  ],
  routed: false,
  ...over,
});

test("drives stay straight; flights become great-circle arcs", () => {
  const [drive, flight] = legFeatures([leg({}), leg({ id: 2, mode: "flight" })]).features;
  expect(drive?.geometry.coordinates).toHaveLength(2);
  expect(flight?.geometry.coordinates.length).toBeGreaterThan(10);
  expect(flight?.properties).toMatchObject({ trip_id: 10, leg_id: 2, mode: "flight" });
});

test("a great circle starts and ends at its airports and bulges poleward", () => {
  const arc = greatCircle([-97, 38], [2, 49]);
  expect(arc[0]?.[0]).toBeCloseTo(-97);
  expect(arc.at(-1)?.[1]).toBeCloseTo(49);
  expect(Math.max(...arc.map((p) => p[1] ?? 0))).toBeGreaterThan(49);
});

test("an arc across the antimeridian stays continuous", () => {
  const arc = greatCircle([170, -40], [-150, 20]);
  const jumps = arc.slice(1).map((p, i) => Math.abs((p[0] ?? 0) - (arc[i]?.[0] ?? 0)));
  expect(Math.max(...jumps)).toBeLessThan(20);
});

test("a trip's bounds cover its stops and legs only", () => {
  const data = {
    trips: [],
    truncated: false,
    stops: [
      { id: 1, trip_id: 10, kind: "visit", name: "", lon: -100, lat: 35 },
      { id: 2, trip_id: 11, kind: "visit", name: "", lon: 50, lat: 50 },
    ],
    legs: [leg({})],
  };
  expect(tripBounds(data, 10)).toEqual([
    [-100, 35],
    [-96, 39],
  ]);
  expect(tripBounds(data, 99)).toBeNull();
  // Several trips (the list's selection, `f`): one box around all of them.
  expect(tripBounds(data, [10, 11, 99])).toEqual([
    [-100, 35],
    [50, 50],
  ]);
  expect(tripBounds(data, [])).toBeNull();
});

test("the view's bbox is rounded and wrapped into the API's range", () => {
  expect(toBbox(-97.123456, 37.5, -96.5, 38.25)).toBe("-97.1235,37.5,-96.5,38.25");
  expect(toBbox(170, 10, 190, 20)).toBe("170,10,-170,20");
  expect(toBbox(-300, -95, 300, 95)).toBe("-180,-90,180,90");
});

test("a map pick answers the form that asked once, then clears", () => {
  const got: number[] = [];
  useMapStore.getState().startPick("the stop", (p) => got.push(p.lon));
  expect(useMapStore.getState().pick?.label).toBe("the stop");
  useMapStore.getState().completePick({ lon: 5, lat: 6 });
  useMapStore.getState().completePick({ lon: 7, lat: 8 });
  expect(got).toEqual([5]);
  expect(useMapStore.getState().pick).toBeNull();
});
