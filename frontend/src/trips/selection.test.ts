import {
  EMPTY_SELECTION,
  extend,
  highlighted,
  moveCursor,
  prune,
  type Selection,
  targets,
  toggle,
} from "./selection";

const IDS = [10, 11, 12, 13, 14];
const at = (cursor: number | null, selected: number[] = [], anchor: number | null = null) =>
  ({ cursor, selected, anchor }) satisfies Selection;

test("the first j lands on the first row, the first k on the last; moves clamp at the ends", () => {
  expect(moveCursor(EMPTY_SELECTION, IDS, 1).cursor).toBe(10);
  expect(moveCursor(EMPTY_SELECTION, IDS, -1).cursor).toBe(14);
  expect(moveCursor(at(10), IDS, -1).cursor).toBe(10);
  expect(moveCursor(at(14), IDS, 1).cursor).toBe(14);
  expect(moveCursor(at(12), IDS, 1).cursor).toBe(13);
  expect(moveCursor(at(12), [], 1).cursor).toBeNull();
});

test("a cursor on a trip that left the list starts again from the top", () => {
  expect(moveCursor(at(99), IDS, 1).cursor).toBe(10);
});

test("x toggles the cursor's trip and keeps the selection order", () => {
  const one = toggle(at(12), 12);
  expect(one.selected).toEqual([12]);
  expect(toggle(at(11, [12]), 11).selected).toEqual([12, 11]);
  expect(toggle(one, 12).selected).toEqual([]);
  expect(toggle(at(null), null)).toEqual(at(null));
});

test("Shift+j/k selects the range from the anchor and shrinks when moving back", () => {
  let s = extend(at(11), IDS, 1);
  expect(s).toEqual(at(12, [11, 12], 11));
  s = extend(s, IDS, 1);
  expect(s.selected).toEqual([11, 12, 13]);
  s = extend(s, IDS, -1);
  expect(s.selected).toEqual([11, 12]);
  s = extend(s, IDS, -1);
  s = extend(s, IDS, -1);
  expect(s).toEqual(at(10, [10, 11], 11));
});

test("extending keeps trips selected before the range began", () => {
  const s = extend(at(12, [14]), IDS, -1);
  expect(s.selected).toEqual([14, 11, 12]);
});

test("a plain move or toggle ends the range", () => {
  const s = moveCursor(extend(at(11), IDS, 1), IDS, 1);
  expect(s.anchor).toBeNull();
  expect(s.selected).toEqual([11, 12]);
});

test("prune drops trips that are no longer listed and keeps the same object otherwise", () => {
  const s = at(13, [10, 13, 14], 10);
  expect(prune(s, IDS)).toBe(s);
  expect(prune(s, [10, 11])).toEqual(at(null, [10], 10));
});

test("actions apply to the selection, else the cursor; the map highlights both", () => {
  expect(targets(at(12, [10, 11]))).toEqual([10, 11]);
  expect(targets(at(12))).toEqual([12]);
  expect(targets(EMPTY_SELECTION)).toEqual([]);
  expect(highlighted(at(12, [10]))).toEqual([10, 12]);
  expect(highlighted(at(10, [10]))).toEqual([10]);
  expect(highlighted(EMPTY_SELECTION)).toEqual([]);
});
