/**
 * The trip list's keyboard cursor and multi-selection (ui.md §18.4). It spans the two panels
 * (the list highlights rows, the map highlights the same trips), so it lives in a small zustand
 * store rather than component state; it is not in the URL because it is a working set, not a
 * view anyone would bookmark. The rules are pure functions over the list's ordered ids, so
 * they are unit-tested without React.
 */
import { create } from "zustand";

export type Selection = {
  /** The trip the cursor is on (j/k), or null before the first move. */
  cursor: number | null;
  /** Selected trip ids, in the order they were selected. */
  selected: number[];
  /** Where a Shift+j/k range started (the cursor when extending began). */
  anchor: number | null;
};

export const EMPTY_SELECTION: Selection = { cursor: null, selected: [], anchor: null };

/** Move the cursor by `step` rows (clamped to the list; the first move lands on the first row). */
export function moveCursor(state: Selection, ids: number[], step: number): Selection {
  if (!ids.length) return { ...state, cursor: null };
  const at = state.cursor === null ? -1 : ids.indexOf(state.cursor);
  const next =
    at === -1 ? (step > 0 ? 0 : ids.length - 1) : Math.min(ids.length - 1, Math.max(0, at + step));
  return { ...state, cursor: ids[next] ?? null, anchor: null };
}

/** Select or deselect one trip (the cursor's, by default). */
export function toggle(state: Selection, id: number | null): Selection {
  if (id === null) return state;
  const selected = state.selected.includes(id)
    ? state.selected.filter((s) => s !== id)
    : [...state.selected, id];
  return { ...state, selected, anchor: null };
}

/**
 * Shift+j/k: move the cursor and select every row between the anchor and the new cursor,
 * keeping trips selected before the range began. Moving back toward the anchor shrinks it.
 */
export function extend(state: Selection, ids: number[], step: number): Selection {
  if (!ids.length) return state;
  const moved = moveCursor(state, ids, step);
  const anchor = state.anchor ?? state.cursor ?? moved.cursor;
  if (moved.cursor === null || anchor === null) return state;
  const a = ids.indexOf(anchor);
  const b = ids.indexOf(moved.cursor);
  const range = ids.slice(Math.min(a, b), Math.max(a, b) + 1);
  const previous =
    state.anchor !== null && state.cursor !== null ? rangeIds(ids, state.anchor, state.cursor) : [];
  const kept = state.selected.filter((id) => !previous.includes(id));
  const selected = [...kept, ...range.filter((id) => !kept.includes(id))];
  return { cursor: moved.cursor, selected, anchor };
}

function rangeIds(ids: number[], from: number, to: number): number[] {
  const a = ids.indexOf(from);
  const b = ids.indexOf(to);
  if (a === -1 || b === -1) return [];
  return ids.slice(Math.min(a, b), Math.max(a, b) + 1);
}

/** Forget trips that are no longer listed (the filter changed): a selection only ever holds
 * rows the user can see, so "N selected" and the bulk action mean the same trips. */
export function prune(state: Selection, ids: number[]): Selection {
  const listed = new Set(ids);
  const selected = state.selected.filter((id) => listed.has(id));
  const cursor = state.cursor !== null && listed.has(state.cursor) ? state.cursor : null;
  const anchor = state.anchor !== null && listed.has(state.anchor) ? state.anchor : null;
  if (
    selected.length === state.selected.length &&
    cursor === state.cursor &&
    anchor === state.anchor
  )
    return state;
  return { cursor, selected, anchor };
}

/** The trips an action applies to: the selection, else the cursor's trip, else none. */
export function targets(state: Selection): number[] {
  if (state.selected.length) return state.selected;
  return state.cursor === null ? [] : [state.cursor];
}

/** Trips the map draws highlighted: the selection plus the cursor's trip. */
export function highlighted(state: Selection): number[] {
  return state.cursor === null || state.selected.includes(state.cursor)
    ? state.selected
    : [...state.selected, state.cursor];
}

type SelectionStore = Selection & {
  /** Bumped by `f`; the trips map layer fits the highlighted trips when it changes. */
  fitRequest: number;
  apply: (change: (state: Selection) => Selection) => void;
  selectAll: (ids: number[]) => void;
  clear: () => void;
  requestFit: () => void;
};

export const useSelectionStore = create<SelectionStore>((set, get) => ({
  ...EMPTY_SELECTION,
  fitRequest: 0,
  apply: (change) => {
    const { cursor, selected, anchor } = get();
    const next = change({ cursor, selected, anchor });
    if (next.cursor !== cursor || next.selected !== selected || next.anchor !== anchor) set(next);
  },
  selectAll: (ids) => set({ selected: [...ids], anchor: null }),
  clear: () => set({ selected: [], anchor: null }),
  requestFit: () => set((s) => ({ fitRequest: s.fitRequest + 1 })),
}));
