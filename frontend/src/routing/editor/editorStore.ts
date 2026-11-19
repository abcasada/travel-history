/**
 * The drag editor's session (routing.md §13.4): the line being reshaped, undo/redo, and the one
 * routing request allowed in flight. The map controller turns gestures into the calls below;
 * the toolbar (RouteEditor) shows the state and saves. Routing goes only through our proxy
 * (`proposeRoute`), whose per-user cache lets the save endpoint verify each routed piece (D-93).
 * Nothing here re-routes a saved version: saving always creates a new one (rule 5).
 */
import { create } from "zustand";
import { ApiError } from "../../api/client";
import { errorKind, serverMessage } from "../../api/errors";
import {
  proposeRoute,
  type RouteDetailOut,
  type RouteProposalOut,
  saveEditedRoute,
} from "../../api/generated";
import { type Coord, pt } from "./geometry";
import {
  appendFirst,
  applyRoute,
  controlPoints,
  deleteWithoutRoute,
  type EditorState,
  emptyState,
  insertAnchor,
  moveAlone,
  needsRoute,
  planAppend,
  planDelete,
  planDragLine,
  planMove,
  type RoutePlan,
  toPieces,
} from "./model";

/** Enough steps for a long session; each state shares its unchanged points with the others. */
const MAX_UNDO = 100;

type Store = {
  legId: number | null;
  state: EditorState;
  past: EditorState[];
  future: EditorState[];
  busy: boolean;
  error: string | null;
  /** Bumped when the map must redraw from the state (e.g. a failed drag snaps back). */
  revision: number;
  start: (legId: number, state: EditorState) => void;
  stop: () => void;
  undo: () => void;
  redo: () => void;
  move: (index: number, to: Coord, zoom: number) => Promise<void>;
  dragLine: (grabbed: Coord, to: Coord, zoom: number) => Promise<void>;
  append: (to: Coord) => Promise<void>;
  remove: (index: number, zoom: number) => Promise<void>;
  insert: (at: Coord) => void;
  save: (note: string) => Promise<RouteDetailOut | null>;
};

const round6 = (c: Coord): [number, number] => [
  Math.round(c[0] * 1e6) / 1e6,
  Math.round(c[1] * 1e6) / 1e6,
];

function routingMessage(error: unknown): string {
  if (errorKind(error) === "rate-limited") return "Routing too fast; wait a moment and try again.";
  return serverMessage(error) ?? "The route could not be updated.";
}

export const useEditorStore = create<Store>((set, get) => {
  function commit(next: EditorState) {
    const { state, past } = get();
    set({ state: next, past: [...past, state].slice(-MAX_UNDO), future: [], error: null });
  }

  async function route(plan: RoutePlan | null) {
    if (!plan || get().busy) return;
    const before = get().state;
    if (!needsRoute(plan)) {
      commit(moveAlone(before, pt(plan.chain, 0), pt(plan.targets, 0)));
      return;
    }
    const waypoints = plan.targets.map(round6);
    set({ busy: true, error: null });
    let answer: RouteProposalOut;
    try {
      answer = await proposeRoute({ waypoints, profile: "auto" });
    } catch (error) {
      set((s) => ({ busy: false, error: routingMessage(error), revision: s.revision + 1 }));
      return;
    }
    // The user may have undone or left while the request was out: apply only to the same line.
    if (get().state !== before) {
      set({ busy: false });
      return;
    }
    const line = answer.routes[0]?.geometry.coordinates as [number, number][] | undefined;
    if (!line?.length) {
      set((s) => ({ busy: false, error: "No route came back.", revision: s.revision + 1 }));
      return;
    }
    const { engine, attribution } = answer.provenance;
    commit(applyRoute(before, plan, line, { kind: "proposal", waypoints, engine, attribution }));
    set({ busy: false });
  }

  return {
    legId: null,
    state: emptyState(),
    past: [],
    future: [],
    busy: false,
    error: null,
    revision: 0,
    start: (legId, state) =>
      set({ legId, state, past: [], future: [], busy: false, error: null, revision: 0 }),
    stop: () => set({ legId: null, state: emptyState(), past: [], future: [], error: null }),
    undo: () => {
      const { past, state, future, busy } = get();
      if (busy || past.length === 0) return;
      set({ state: past[past.length - 1], past: past.slice(0, -1), future: [state, ...future] });
    },
    redo: () => {
      const { past, state, future, busy } = get();
      if (busy || future.length === 0) return;
      set({ state: future[0], past: [...past, state], future: future.slice(1) });
    },
    move: (index, to, zoom) => route(planMove(get().state, index, to, zoom)),
    dragLine: (grabbed, to, zoom) => route(planDragLine(get().state, grabbed, to, zoom)),
    append: async (to) => {
      if (get().busy) return;
      const state = get().state;
      if (state.points.length === 0) {
        commit(appendFirst(state, to));
        return;
      }
      await route(planAppend(state, to));
    },
    remove: async (index, zoom) => {
      if (get().busy) return;
      const state = get().state;
      const plan = planDelete(state, index, zoom);
      if (plan) await route(plan);
      else commit(deleteWithoutRoute(state, index, zoom));
    },
    insert: (at) => {
      if (!get().busy) commit(insertAnchor(get().state, at));
    },
    save: async (note) => {
      const { legId, state } = get();
      if (legId === null || state.points.length < 2) return null;
      const waypoints = controlPoints(state).map((c) => [c[0], c[1]]);
      let expired = new Set<number>();
      // A session can outlast the 10-minute proposal cache: the server lists the expired
      // pieces (409) and they are sent once more as drawn points that keep their credit.
      for (let attempt = 0; attempt < 2; attempt++) {
        const { pieces, pieceSources } = toPieces(state, expired);
        try {
          return await saveEditedRoute(legId, { pieces, waypoints, note });
        } catch (error) {
          const conflict = error instanceof ApiError && error.status === 409;
          const body = conflict ? (error.body as { expired?: number[] } | undefined) : undefined;
          if (attempt > 0 || !body?.expired) throw error;
          expired = new Set(body.expired.map((position) => pt(pieceSources, position)));
        }
      }
      return null;
    },
  };
});
