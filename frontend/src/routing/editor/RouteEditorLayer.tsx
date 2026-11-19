import { useEffect, useRef } from "react";
import { useMap } from "react-map-gl/maplibre";
import { useMapStore } from "../../map/store";
import { RouteEditorController } from "./controller";
import { useEditorStore } from "./editorStore";

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
    return () => {
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
