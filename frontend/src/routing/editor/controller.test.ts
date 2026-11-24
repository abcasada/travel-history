import type { Map as MapLibreMap } from "maplibre-gl";
import {
  ANCHORS_ID,
  type EditorActions,
  LINE_HIT_ID,
  LONG_PRESS_MS,
  RouteEditorController,
} from "./controller";
import type { Coord } from "./geometry";
import { fromLine } from "./model";

// The controller only needs MapLibre's Popup class at import; the tests pass their own popup.
vi.mock("maplibre-gl", () => ({ Popup: class {} }));

/** A screen point with the two methods the controller uses. */
type P = { x: number; y: number; dist: (o: P) => number; equals: (o: P) => boolean };
const P = (x: number, y: number): P => ({
  x,
  y,
  dist: (o) => Math.hypot(o.x - x, o.y - y),
  equals: (o) => o.x === x && o.y === y,
});

/** Screen pixels are 100 per degree, so test points read easily. */
const toScreen = ([lon, lat]: [number, number]) => P(lon * 100, -lat * 100);
const toLngLat = (p: P) => ({ lng: p.x / 100, lat: -p.y / 100 });

type Handler = { type: string; layer?: string; fn: (e: unknown) => void };

class FakeMap {
  handlers: Handler[] = [];
  sources = new Map<
    string,
    { setData: ReturnType<typeof vi.fn>; updateData: ReturnType<typeof vi.fn> }
  >();
  layers = new Set<string>();
  hits: string[] = [];
  dragPan = { enable: vi.fn(), disable: vi.fn() };
  canvas = { style: { cursor: "" } };

  on(type: string, a: unknown, b?: unknown) {
    if (typeof a === "string") this.handlers.push({ type, layer: a, fn: b as Handler["fn"] });
    else this.handlers.push({ type, fn: a as Handler["fn"] });
  }
  once(type: string, fn: Handler["fn"]) {
    const wrapped = (e: unknown) => {
      this.off(type, wrapped);
      fn(e);
    };
    this.on(type, wrapped);
  }
  off(type: string, a: unknown, b?: unknown) {
    const fn = typeof a === "string" ? b : a;
    this.handlers = this.handlers.filter((h) => !(h.type === type && h.fn === fn));
  }
  /** Fires `type`; layer handlers run when their layer is under the pointer (`hitLayers`). */
  fire(type: string, event: Record<string, unknown>, hitLayers: string[] = []) {
    for (const h of [...this.handlers]) {
      if (h.type !== type) continue;
      if (h.layer && !hitLayers.includes(h.layer)) continue;
      h.fn(event);
    }
  }
  addSource(id: string) {
    this.sources.set(id, { setData: vi.fn(), updateData: vi.fn() });
  }
  getSource(id: string) {
    return this.sources.get(id);
  }
  addLayer(layer: { id: string }) {
    this.layers.add(layer.id);
  }
  getLayer(id: string) {
    return this.layers.has(id) ? { id } : undefined;
  }
  removeLayer(id: string) {
    this.layers.delete(id);
  }
  removeSource(id: string) {
    this.sources.delete(id);
  }
  queryRenderedFeatures() {
    return this.hits.map((id) => ({ layer: { id }, properties: { anchorIndex: this.hitAnchor } }));
  }
  hitAnchor = 0;
  getZoom() {
    return 12;
  }
  project(c: [number, number]) {
    return toScreen(c);
  }
  getCanvas() {
    return this.canvas;
  }
}

const LINE: [number, number][] = [
  [-97, 38],
  [-96.5, 38.2],
  [-96, 38],
];

function setup() {
  const map = new FakeMap();
  const actions = {
    move: vi.fn(),
    dragLine: vi.fn(),
    append: vi.fn(),
    remove: vi.fn(),
    insert: vi.fn(),
    blocked: vi.fn(() => false),
  } satisfies EditorActions;
  const popups: { at: Coord; content: HTMLElement; remove: ReturnType<typeof vi.fn> }[] = [];
  const controller = new RouteEditorController(
    map as unknown as MapLibreMap,
    actions,
    (_map, at, content) => {
      const popup = { at, content, remove: vi.fn() };
      popups.push(popup);
      return popup;
    },
  );
  // the ends and the middle are anchors; the middle one only from zoom 10
  const state = fromLine(LINE, { kind: "drawn" }, [LINE[0], LINE[2]] as [number, number][]);
  const points = state.points.map((p, i) => (i === 1 ? { ...p, zoom: 10 } : p));
  controller.render({ ...state, points });
  return { map, actions, popups, controller };
}

/** A touch event at `points` (screen), MapLibre-style: the first point is `point`. */
function touch(points: P[], features?: { anchorIndex: number }[]) {
  const first = points[0] ?? P(0, 0); // touchend may report no finger
  return {
    point: first,
    points,
    lngLat: toLngLat(first),
    features: features?.map((properties) => ({ properties })),
    preventDefault: vi.fn(),
    originalEvent: {},
  };
}

function click(at: P, shiftKey = false) {
  return { point: at, lngLat: toLngLat(at), originalEvent: { shiftKey } };
}

afterEach(() => {
  vi.useRealTimers();
});

test("clicking an anchor opens its popup; its button removes the point", () => {
  const { map, actions, popups } = setup();
  map.hits = [ANCHORS_ID];
  map.hitAnchor = 1;
  map.fire("click", click(toScreen([-96.5, 38.2])));
  expect(popups).toHaveLength(1);
  const popup = popups[0];
  expect(popup?.at).toEqual([-96.5, 38.2]);
  expect(popup?.content.textContent).toContain("Shape point");
  const [remove, keep] = popup?.content.querySelectorAll("button") ?? [];
  expect(remove?.textContent).toBe("Remove this point");
  expect(keep?.textContent).toBe("Keep as a fixed point");
  remove?.click();
  expect(actions.remove).toHaveBeenCalledWith(1, 12);
  expect(popup?.remove).toHaveBeenCalled();
  expect(actions.append).not.toHaveBeenCalled();
});

test("a fixed point's popup can keep a shape point; a click elsewhere only closes it", () => {
  const { map, actions, popups } = setup();
  map.hits = [ANCHORS_ID];
  map.hitAnchor = 0;
  map.fire("click", click(toScreen([-97, 38])));
  expect(popups[0]?.content.textContent).toContain("Fixed point");
  expect(popups[0]?.content.querySelectorAll("button")).toHaveLength(1);
  map.hits = [];
  map.fire("click", click(P(0, 0)));
  expect(popups[0]?.remove).toHaveBeenCalled();
  expect(actions.append).not.toHaveBeenCalled();

  map.hits = [ANCHORS_ID];
  map.fire("click", click(toScreen([-97, 38])));
  popups[1]?.content.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  expect(popups[1]?.remove).toHaveBeenCalled();

  map.hitAnchor = 1;
  map.fire("click", click(toScreen([-96.5, 38.2])));
  popups[2]?.content.querySelectorAll("button")[1]?.click();
  expect(actions.insert).toHaveBeenCalledWith([-96.5, 38.2]);
});

test("shift-click still removes without a popup", () => {
  const { map, actions, popups } = setup();
  map.hits = [ANCHORS_ID];
  map.hitAnchor = 2;
  map.fire("click", click(toScreen([-96, 38]), true));
  expect(actions.remove).toHaveBeenCalledWith(2, 12);
  expect(popups).toHaveLength(0);
});

test("dragging an anchor with a finger moves it on release", () => {
  const { map, actions } = setup();
  const start = toScreen([-96.5, 38.2]);
  const e = touch([start], [{ anchorIndex: 1 }]);
  map.fire("touchstart", e, [ANCHORS_ID, LINE_HIT_ID]);
  expect(e.preventDefault).toHaveBeenCalled();
  expect(map.dragPan.disable).toHaveBeenCalled();
  map.fire("touchmove", touch([P(start.x + 30, start.y)]));
  map.fire("touchend", touch([]));
  expect(actions.move).toHaveBeenCalledWith(1, [-96.2, 38.2], 12);
  expect(map.dragPan.enable).toHaveBeenCalled();
  // the click the browser sends after the touch neither appends nor opens a popup
  map.hits = [];
  map.fire("click", click(P(start.x + 30, start.y)));
  expect(actions.append).not.toHaveBeenCalled();
});

test("tapping an anchor opens its popup; a long press is not a right-click delete", () => {
  const { map, actions, popups } = setup();
  const at = toScreen([-96, 38]);
  map.fire("touchstart", touch([at], [{ anchorIndex: 2 }]), [ANCHORS_ID]);
  map.fire("touchmove", touch([P(at.x + 2, at.y + 1)]));
  map.fire(
    "contextmenu",
    { preventDefault: vi.fn(), features: [{ properties: { anchorIndex: 2 } }] },
    [ANCHORS_ID],
  );
  map.fire("touchend", touch([]));
  expect(actions.move).not.toHaveBeenCalled();
  expect(actions.remove).not.toHaveBeenCalled();
  expect(popups).toHaveLength(1);
  expect(popups[0]?.at).toEqual([-96, 38]);
});

test("a second finger cancels an anchor drag", () => {
  const { map, actions } = setup();
  const at = toScreen([-96, 38]);
  map.fire("touchstart", touch([at], [{ anchorIndex: 2 }]), [ANCHORS_ID]);
  map.fire("touchmove", touch([P(at.x + 40, at.y), P(at.x - 40, at.y)]));
  map.fire("touchend", touch([]));
  expect(actions.move).not.toHaveBeenCalled();
  expect(map.dragPan.enable).toHaveBeenCalled();
});

test("holding the line grabs it and dragging reshapes; a swipe pans instead", () => {
  vi.useFakeTimers();
  const { map, actions } = setup();
  const on = toScreen([-96.75, 38.1]);
  // a swipe along the line: the map pans, nothing is grabbed
  map.fire("touchstart", touch([on]), [LINE_HIT_ID]);
  map.fire("touchmove", touch([P(on.x + 20, on.y)]));
  vi.advanceTimersByTime(LONG_PRESS_MS);
  expect(map.dragPan.disable).not.toHaveBeenCalled();
  map.fire("touchend", touch([]));

  // held still: grabbed, then dragged
  map.fire("touchstart", touch([on]), [LINE_HIT_ID]);
  vi.advanceTimersByTime(LONG_PRESS_MS);
  expect(map.dragPan.disable).toHaveBeenCalled();
  map.fire("touchmove", touch([P(on.x, on.y - 50)]));
  map.fire("touchend", touch([]));
  expect(actions.dragLine).toHaveBeenCalledWith([-96.75, 38.1], [-96.75, 38.6], 12);
});

test("holding the line without moving keeps a point there", () => {
  vi.useFakeTimers();
  const { map, actions } = setup();
  const on = toScreen([-96.25, 38.1]);
  map.fire("touchstart", touch([on]), [LINE_HIT_ID]);
  vi.advanceTimersByTime(LONG_PRESS_MS);
  map.fire("touchend", touch([]));
  expect(actions.insert).toHaveBeenCalledWith([-96.25, 38.1]);
  expect(actions.dragLine).not.toHaveBeenCalled();
});

test("no touch editing while a route request is out", () => {
  const { map, actions } = setup();
  actions.blocked.mockReturnValue(true);
  const at = toScreen([-96, 38]);
  const e = touch([at], [{ anchorIndex: 2 }]);
  map.fire("touchstart", e, [ANCHORS_ID]);
  expect(e.preventDefault).not.toHaveBeenCalled();
  expect(map.dragPan.disable).not.toHaveBeenCalled();
});
