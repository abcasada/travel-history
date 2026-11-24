import { describeSources } from "./sources";

test("each source of a hand-edited version says what it is and whether it was checked", () => {
  expect(
    describeSources([
      {
        source: "proposal",
        engine: "valhalla",
        engine_version: "3.9.1",
        data_date: "2026-11-01",
        verified: true,
        points: 1204,
      },
      {
        source: "version",
        route_id: 7,
        version: 2,
        kind: "map_matched",
        engine: "",
        verified: true,
        points: 31,
      },
      { source: "drawn", engine: "", verified: false, points: 1 },
      { source: "drawn", engine: "ors", verified: false, points: 88 },
    ]),
  ).toEqual([
    "Valhalla (self-hosted) route, 1,204 points, checked",
    "version 2, map_matched, 31 points",
    "1 point drawn by hand, not checked",
    "88 points sent by the editor (openrouteservice route that had expired), not checked",
  ]);
});

test("versions without sources (proposals, map matching, older rows) list nothing", () => {
  expect(describeSources([])).toEqual([]);
  expect(describeSources(undefined)).toEqual([]);
});

test("an unknown engine or source is shown as it is", () => {
  expect(
    describeSources([
      { source: "proposal", engine: "graphhopper", verified: true, points: 2 },
      { source: "future", points: 3 },
    ]),
  ).toEqual(["graphhopper route, 2 points, checked", "3 points, not checked"]);
});
