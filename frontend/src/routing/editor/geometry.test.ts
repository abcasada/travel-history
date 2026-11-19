// Cases follow gpx.studio's tests for anchors.rs and simplify.rs (MIT; see geometry.ts).
import {
  anchorZoom,
  closestPointIndexIn,
  closestSegment,
  computeAnchors,
  crossarc,
  distance,
  MAX_ANCHOR_ZOOM,
  ramerDouglasPeucker,
} from "./geometry";

test("the zoom of an anchor depends on the size of its detail", () => {
  expect(anchorZoom(45, null)).toBe(0);
  // 2^13 m is close to the radius of the earth divided by 1 km
  expect(anchorZoom(0, 1000)).toBe(13);
  expect(anchorZoom(0, 10)).toBeGreaterThan(anchorZoom(0, 1000));
  expect(anchorZoom(0, 1e-9)).toBe(MAX_ANCHOR_ZOOM);
  expect(anchorZoom(0, 1e9)).toBe(0);
  // the poles give neither NaN nor a crash
  expect(anchorZoom(90, 10)).toBe(0);
});

test("a straight line's anchors are its ends", () => {
  const line = Array.from({ length: 10 }, (_, i) => [i * 0.001, 0] as const);
  expect(computeAnchors(line)).toEqual([
    { index: 0, zoom: 0 },
    { index: 9, zoom: 0 },
  ]);
});

test("anchors keep the corners, small bumps only at high zoom", () => {
  const points = [
    [0, 0],
    [0.01, 0],
    [0.02, 0],
    [0.02, 0.01],
    [0.02, 0.02],
    [0.02, 0.020005],
    [0.02, 0.03],
  ] as const;
  const anchors = computeAnchors(points);
  expect(anchors.map((a) => a.index)).toEqual([0, 2, 6]);
  expect(anchors[0]?.zoom).toBe(0);
  expect(anchors[2]?.zoom).toBe(0);
  expect(anchors[1]?.zoom).toBeGreaterThan(0);
});

test("short lines", () => {
  expect(computeAnchors([])).toEqual([]);
  expect(computeAnchors([[1, 2]])).toEqual([{ index: 0, zoom: 0 }]);
  expect(
    computeAnchors([
      [1, 2],
      [1, 2.1],
    ]).map((a) => a.index),
  ).toEqual([0, 1]);
});

test("Ramer-Douglas-Peucker keeps the ends and gives the kept points in order", () => {
  const zigzag = Array.from({ length: 2000 }, (_, i) => [i * 0.0001, (i % 2) * 0.001] as const);
  const kept = ramerDouglasPeucker(zigzag, 1);
  expect(kept[0]).toEqual({ index: 0, distance: null });
  expect(kept[kept.length - 1]).toEqual({ index: 1999, distance: null });
  expect(kept.length).toBe(2000);
  expect(kept.every((k, i) => i === 0 || k.index > (kept[i - 1]?.index ?? -1))).toBe(true);
});

test("distances in meters", () => {
  expect(distance([0, 0], [0, 1])).toBeCloseTo(111_195, -1);
  // a point 0.001° north of an east-west segment at the equator is about 111 m away
  expect(crossarc([0, 0], [0.01, 0], [0.005, 0.001])).toBeCloseTo(111.3, 0);
});

test("the closest point of a line, and where a point falls on it", () => {
  const line = [
    [0, 0],
    [0.01, 0],
    [0.02, 0],
  ] as const;
  expect(closestPointIndexIn(line, 0, 3, [0.004, 0.001])).toBe(0);
  expect(closestPointIndexIn(line, 0, 3, [0.0119, 0.001])).toBe(1);
  expect(closestPointIndexIn(line, 1, 3, [0, 0])).toBe(1);
  expect(closestPointIndexIn(line, 2, 2, [0, 0])).toBeUndefined();
  const hit = closestSegment(line, [0.015, 0.002]);
  expect(hit?.segment).toBe(1);
  expect(hit?.at[0]).toBeCloseTo(0.015, 6);
  expect(hit?.at[1]).toBeCloseTo(0, 6);
});
