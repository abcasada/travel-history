import type { MapLayerMouseEvent, MapLibreEvent } from "maplibre-gl";
import { useEffect } from "react";
import { useMap } from "react-map-gl/maplibre";
import { useShortcuts } from "../platform/shortcuts";
import { toBbox, useMapStore } from "./store";

/** While a form asks for a point, the next map click answers it (crosshair cursor, banner,
 * Esc cancels). Rendered inside the map by both shells. */
export function MapPickHandler() {
  const { current: ref } = useMap();
  const pick = useMapStore((s) => s.pick);
  const cancel = useMapStore((s) => s.cancelPick);
  useShortcuts({ Escape: cancel }, pick !== null);

  useEffect(() => {
    const map = ref?.getMap();
    if (!map || !pick) return;
    const canvas = map.getCanvas();
    canvas.style.cursor = "crosshair";
    const onClick = (event: MapLayerMouseEvent) => {
      useMapStore.getState().completePick({ lon: event.lngLat.lng, lat: event.lngLat.lat });
    };
    map.once("click", onClick);
    return () => {
      map.off("click", onClick);
      canvas.style.cursor = "";
    };
  }, [ref, pick]);

  if (!pick) return null;
  return (
    <div className="pointer-events-none absolute inset-x-0 top-2 z-10 flex justify-center">
      <div
        className="pointer-events-auto rounded-md bg-blue-900/90 px-3 py-1.5 text-sm text-white shadow"
        role="status"
      >
        Click the map to place {pick.label}.{" "}
        <button type="button" className="underline" onClick={cancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Keeps the map store's bbox equal to the visible area (for "only trips in view"). */
export function MapViewTracker() {
  const { current: ref } = useMap();
  const setBbox = useMapStore((s) => s.setBbox);
  useEffect(() => {
    const map = ref?.getMap();
    if (!map) return;
    const update = (_?: MapLibreEvent) => {
      const b = map.getBounds();
      setBbox(toBbox(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()));
    };
    if (map.loaded()) update();
    map.on("moveend", update);
    map.on("load", update);
    return () => {
      map.off("moveend", update);
      map.off("load", update);
    };
  }, [ref, setBbox]);
  return null;
}
