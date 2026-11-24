import { ApiError } from "../../api/client";
import type { RouteProposalOut } from "../../api/generated";
import type { Coord } from "./geometry";
import { type EditorState, fromLine, type Source } from "./model";
import {
  MAX_REPROPOSALS,
  RATE_LIMIT_WAIT_MS,
  REPROPOSE_SPACING_MS,
  reproposeExpired,
  sameLine,
} from "./repropose";

const LINE: Coord[] = [
  [-97.33, 37.69],
  [-97.4, 38.0],
  [-97.61, 38.84],
];

const proposal = (n = 0): Source => ({
  kind: "proposal",
  waypoints: [
    [-97.33, 37.69 + n / 1000],
    [-97.61, 38.84],
  ],
  engine: "valhalla",
  attribution: "Route: Valhalla",
});

function answer(line: Coord[]): RouteProposalOut {
  return {
    routes: [{ geometry: { type: "LineString", coordinates: line }, distance: 1, duration: 1 }],
    provenance: { engine: "valhalla", attribution: "Route: Valhalla" },
  } as unknown as RouteProposalOut;
}

/** A line whose points come from `count` proposals (source 1..count), one point each. */
function manySources(count: number): EditorState {
  const sources: Source[] = [{ kind: "drawn" }];
  const points = [];
  for (let n = 0; n < count; n++) {
    sources.push(proposal(n));
    points.push({ lon: -97 - n / 100, lat: 38, zoom: null, src: n + 1, i: 0 });
  }
  return { sources, points };
}

test("sameLine compares only the points the editor uses from that source", () => {
  const state = fromLine(LINE, proposal(), []);
  expect(sameLine(state, 1, LINE)).toBe(true);
  expect(sameLine(state, 1, [...LINE, [-97.7, 39]])).toBe(true);
  expect(sameLine(state, 1, [LINE[0] as Coord, [-97.41, 38], LINE[2] as Coord])).toBe(false);
  expect(sameLine(state, 1, LINE.slice(0, 2))).toBe(false);
  // a source the line doesn't use proves nothing
  expect(sameLine(state, 0, LINE)).toBe(false);
});

test("each expired proposal is asked for again with its own waypoints, spaced out", async () => {
  const state = fromLine(LINE, proposal(), []);
  const propose = vi.fn(async () => answer(LINE));
  const wait = vi.fn(async () => {});
  const drawn = await reproposeExpired(state, [1, 1], { propose, wait });
  expect(drawn).toEqual(new Set());
  expect(propose.mock.calls).toEqual([[{ waypoints: proposal().waypoints, profile: "auto" }]]);
  expect(wait).not.toHaveBeenCalled();

  const many = manySources(3);
  const waits: number[] = [];
  const progress = vi.fn();
  const out = await reproposeExpired(many, [1, 2, 3], {
    propose: async () => answer([[-97, 38]]),
    wait: async (ms) => {
      waits.push(ms);
    },
    progress,
  });
  // source 1's point is (-97, 38), the others differ
  expect(out).toEqual(new Set([2, 3]));
  expect(waits).toEqual([REPROPOSE_SPACING_MS, REPROPOSE_SPACING_MS]);
  expect(progress.mock.calls).toEqual([
    [0, 3],
    [1, 3],
    [2, 3],
  ]);
});

test("a 429 waits and tries once more; other failures fall back to drawn", async () => {
  const state = fromLine(LINE, proposal(), []);
  const limited = new ApiError(429, { detail: "too many requests" });
  const propose = vi.fn().mockRejectedValueOnce(limited).mockResolvedValueOnce(answer(LINE));
  const wait = vi.fn(async () => {});
  expect(await reproposeExpired(state, [1], { propose, wait })).toEqual(new Set());
  expect(wait.mock.calls).toEqual([[RATE_LIMIT_WAIT_MS]]);

  const twice = vi.fn().mockRejectedValue(limited);
  expect(await reproposeExpired(state, [1], { propose: twice, wait })).toEqual(new Set([1]));
  expect(twice).toHaveBeenCalledTimes(2);

  const down = vi.fn().mockRejectedValue(new ApiError(503, {}));
  expect(await reproposeExpired(state, [1], { propose: down, wait })).toEqual(new Set([1]));
  expect(down).toHaveBeenCalledTimes(1);
});

test("over the cap, and anything that isn't a proposal, goes as drawn without a request", async () => {
  const state = manySources(MAX_REPROPOSALS + 2);
  const propose = vi.fn(async () => answer([[-99, 0]]));
  const srcs = Array.from({ length: MAX_REPROPOSALS + 2 }, (_, n) => n + 1);
  const out = await reproposeExpired(state, [0, ...srcs], { propose, wait: async () => {} });
  expect(propose).toHaveBeenCalledTimes(MAX_REPROPOSALS);
  expect(out.has(0)).toBe(true);
  expect(out.has(MAX_REPROPOSALS + 2)).toBe(true);
});
