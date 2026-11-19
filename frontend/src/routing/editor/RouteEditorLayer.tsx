import { useEffect, useRef } from "react";
import { useMap } from "react-map-gl/maplibre";
import { useMapStore } from "../../map/store";
import { RouteEditorController } from "./controller";
import { useEditorStore } from "./editorStore";
import { anchors } from "./model";

/**
 * Map side of the drag editor (lazy, desktop only): attaches the framework-free controller to
 * the shared map and redraws it whenever the editor's line changes. LegRouteLayer renders this
 * instead of the saved route and the proposal while the editor is open.
 */
export default function RouteEditorLayer() {
  const { current: ref } = useMap();
  const state = useEditorStore((s) => s.state);
  const revision = useEditorStore((s) => s.revision);
  const controller = useRef<RouteEditorController | null>(null);

  useEffect(() => {
    const map = ref?.getMap();
    if (!map) return;
    const editor = useEditorStore.getState;
    const created = new RouteEditorController(map, {
      move: (index, to, zoom) => void editor().move(index, to, zoom),
      dragLine: (grabbed, to, zoom) => void editor().dragLine(grabbed, to, zoom),
      append: (to) => void editor().append(to),
      remove: (index, zoom) => void editor().remove(index, zoom),
      insert: (at) => editor().insert(at),
      // a form picking a point on the map takes the click instead
      blocked: () => editor().busy || useMapStore.getState().pick !== null,
    });
    controller.current = created;
    created.render(editor().state);
    // The e2e smoke test (dev server only) needs to know where the visible anchors are drawn.
    if (import.meta.env.DEV) {
      Reflect.set(window, "__routeEditorAnchors", () =>
        anchors(editor().state)
          .filter((a) => map.getZoom() >= a.zoom)
          .map((a) => map.project([a.lon, a.lat]))
          .map((p) => [p.x, p.y]),
      );
    }
    return () => {
      if (import.meta.env.DEV) Reflect.deleteProperty(window, "__routeEditorAnchors");
      created.destroy();
      controller.current = null;
    };
  }, [ref]);

  useEffect(() => {
    // revision: a failed request redraws the unchanged line, so a dragged anchor snaps back
    void revision;
    controller.current?.render(state);
  }, [state, revision]);

  return null;
}
