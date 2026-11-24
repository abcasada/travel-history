/**
 * Saving after the proposal cache expired (routing.md §13.4, D-93 (4), item 27). The save
 * endpoint verifies routed pieces against the caller's own cached proposals, which live ten
 * minutes; a longer editing session gets a 409 listing the expired pieces. Instead of sending
 * those as unverified drawn points straight away, the editor asks `/api/v1/routing/route`
 * again for exactly the same waypoints. When the answer is the same line, the server's cache
 * holds it again and the piece saves as verified; when the roads or the provider changed, the
 * user's line is kept as it is and only that piece falls back to drawn points (with its
 * engine's credit). The line itself is never replaced here: what the user saw is what is saved,
 * and nothing touches a saved version (rule 5).
 */

import { ApiError } from "../../api/client";
import type { RouteProposalOut, RouteRequestIn } from "../../api/generated";
import type { EditorState } from "./model";

/** The proxy allows 10 requests per 10 s per user (bursts of 5): about one a second is safe. */
export const REPROPOSE_SPACING_MS = 1100;
/** After a 429 the editor waits this long and tries once more. */
export const RATE_LIMIT_WAIT_MS = 2000;
/** Beyond this many expired parts the save would take too long; the rest go as drawn. */
export const MAX_REPROPOSALS = 20;

export type ReproposeDeps = {
  propose: (request: RouteRequestIn) => Promise<RouteProposalOut>;
  wait: (ms: number) => Promise<void>;
  /** Called before each request with how many are done and how many there are. */
  progress?: (done: number, total: number) => void;
};

export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * True when `line` (a new answer for source `src`'s waypoints) has, at every index the editor
 * uses from that source, exactly the point the editor holds, so the server's slice of the new
 * cached proposal is the line the user sees.
 */
export function sameLine(
  state: EditorState,
  src: number,
  line: readonly (readonly number[])[],
): boolean {
  let used = false;
  for (const p of state.points) {
    if (p.src !== src) continue;
    used = true;
    const q = line[p.i];
    if (!q || q[0] !== p.lon || q[1] !== p.lat) return false;
  }
  return used;
}

/**
 * Re-proposes the expired proposal sources `srcs` one after another, spaced to stay under the
 * proxy's per-user limit. Returns the sources that must still be sent as drawn points: the
 * ones whose new answer differs, that failed to route, or that are over the cap.
 */
export async function reproposeExpired(
  state: EditorState,
  srcs: Iterable<number>,
  deps: ReproposeDeps,
): Promise<Set<number>> {
  const asDrawn = new Set<number>();
  const todo: number[] = [];
  for (const src of new Set(srcs)) {
    const source = state.sources[src];
    if (source?.kind === "proposal" && todo.length < MAX_REPROPOSALS) todo.push(src);
    else asDrawn.add(src);
  }
  for (const [n, src] of todo.entries()) {
    const source = state.sources[src];
    if (source?.kind !== "proposal") continue;
    deps.progress?.(n, todo.length);
    if (n > 0) await deps.wait(REPROPOSE_SPACING_MS);
    const answer = await proposeOnce(deps, { waypoints: source.waypoints, profile: "auto" });
    const line = answer?.routes[0]?.geometry.coordinates as number[][] | undefined;
    if (!line || !sameLine(state, src, line)) asDrawn.add(src);
  }
  return asDrawn;
}

async function proposeOnce(
  deps: ReproposeDeps,
  request: RouteRequestIn,
): Promise<RouteProposalOut | null> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return await deps.propose(request);
    } catch (error) {
      const limited = error instanceof ApiError && error.status === 429;
      if (!limited || attempt > 0) return null;
      await deps.wait(RATE_LIMIT_WAIT_MS);
    }
  }
  return null;
}
