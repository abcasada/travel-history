import { stubFetch } from "../../test/fetch";
import { useEditorStore } from "./editorStore";
import type { Coord } from "./geometry";
import { coords, fromDrawn } from "./model";

const START: Coord = [-97.33, 37.69];
const END: Coord = [-97.61, 38.84];
const ROUTED: Coord[] = [
  [-97.33, 37.6901],
  [-97.4, 38.0],
  [-97.5, 38.2],
  [-97.61, 38.8401],
];

function answer(line: Coord[] = ROUTED, engine = "valhalla") {
  return {
    code: "Ok",
    routes: [
      {
        geometry: { type: "LineString", coordinates: line },
        distance: 1,
        duration: 1,
        legs: [],
      },
    ],
    waypoints: [],
    provenance: {
      engine,
      engine_version: "3.9.1",
      data_date: null,
      attribution: "Route: Valhalla, data © OpenStreetMap contributors",
      produced_at: "2026-11-18T10:00:00Z",
    },
    cached: false,
  };
}

const PROPOSE = { method: "POST", path: "/api/v1/routing/route", body: answer() };
const bodies = (mock: ReturnType<typeof stubFetch>, path: string) =>
  mock.mock.calls
    .filter(([url]) => new URL(String(url), "http://localhost").pathname === path)
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));

beforeEach(() => {
  useEditorStore.getState().start(200, fromDrawn([START, END]));
});

test("dragging the straight line routes through the new place, rounded to 6 decimals", async () => {
  const mock = stubFetch([PROPOSE]);
  await useEditorStore.getState().dragLine([-97.47, 38.26], [-97.40000012, 38.0000004], 10);
  expect(bodies(mock, "/api/v1/routing/route")).toEqual([
    { waypoints: [START, [-97.4, 38], END], profile: "auto" },
  ]);
  const { state, past, busy, error } = useEditorStore.getState();
  expect(coords(state)).toEqual(ROUTED);
  expect([past.length, busy, error]).toEqual([1, false, null]);
});

test("undo and redo step through the edits", async () => {
  stubFetch([PROPOSE]);
  const before = useEditorStore.getState().state;
  await useEditorStore.getState().move(1, [-97.6, 38.9], 10);
  const after = useEditorStore.getState().state;
  useEditorStore.getState().undo();
  expect(useEditorStore.getState().state).toBe(before);
  expect(useEditorStore.getState().future).toHaveLength(1);
  useEditorStore.getState().redo();
  expect(useEditorStore.getState().state).toBe(after);
  // a new edit drops what could be redone
  useEditorStore.getState().undo();
  useEditorStore.getState().insert([-97.47, 38.26]);
  expect(useEditorStore.getState().future).toEqual([]);
});

test("a failed request keeps the line, says why and redraws", async () => {
  stubFetch([
    {
      method: "POST",
      path: "/api/v1/routing/route",
      status: 422,
      body: { detail: "no road route connects these points" },
    },
  ]);
  const before = useEditorStore.getState().state;
  await useEditorStore.getState().move(1, [-97.6, 38.9], 10);
  const s = useEditorStore.getState();
  expect(s.state).toBe(before);
  expect(s.error).toBe("no road route connects these points");
  expect(s.revision).toBe(1);
  expect(s.past).toEqual([]);
});

test("one request at a time: edits while routing are ignored", async () => {
  const mock = stubFetch([PROPOSE]);
  const first = useEditorStore.getState().move(1, [-97.6, 38.9], 10);
  expect(useEditorStore.getState().busy).toBe(true);
  await useEditorStore.getState().move(0, [-97.3, 37.6], 10);
  useEditorStore.getState().undo();
  await first;
  expect(bodies(mock, "/api/v1/routing/route")).toHaveLength(1);
  expect(useEditorStore.getState().past).toHaveLength(1);
});

test("appending to an empty editor starts a line without routing", async () => {
  const mock = stubFetch([PROPOSE]);
  useEditorStore.getState().start(200, fromDrawn([]));
  await useEditorStore.getState().append(START);
  expect(coords(useEditorStore.getState().state)).toEqual([START]);
  await useEditorStore.getState().append(END);
  expect(bodies(mock, "/api/v1/routing/route")).toEqual([
    { waypoints: [START, END], profile: "auto" },
  ]);
});

test("saving sends pieces and the fixed anchors; expired proposals are resent as drawn", async () => {
  const saved = { id: 99 };
  const mock = stubFetch([PROPOSE]);
  await useEditorStore.getState().dragLine([-97.47, 38.26], [-97.4, 38.0], 10);
  let calls = 0;
  mock.mockImplementation(async () => {
    calls += 1;
    return calls === 1
      ? new Response(JSON.stringify({ detail: "expired", expired: [0] }), { status: 409 })
      : new Response(JSON.stringify(saved), { status: 201 });
  });
  await expect(useEditorStore.getState().save("by hand")).resolves.toEqual(saved);
  const [first, second] = bodies(mock, "/api/v1/legs/200/routes/edited");
  expect(first).toEqual({
    pieces: [
      {
        source: "proposal",
        waypoints: [START, [-97.4, 38], END],
        start: 0,
        end: 3,
      },
    ],
    waypoints: [ROUTED[0], ROUTED[1], ROUTED[3]],
    note: "by hand",
  });
  expect(second.pieces).toEqual([{ source: "drawn", coordinates: ROUTED, engine: "valhalla" }]);
});
