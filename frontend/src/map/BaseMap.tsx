import "maplibre-gl/dist/maplibre-gl.css";
import "./maplibreWorker";
import type { ReactNode } from "react";
import MapGL, { NavigationControl } from "react-map-gl/maplibre";
import { config } from "../config";

/** The basemap (hosted OpenFreeMap style; attribution comes from the style's sources). */
export function BaseMap({ children }: { children?: ReactNode }) {
  return (
    <MapGL
      initialViewState={config.initialView}
      mapStyle={config.basemapStyle}
      style={{ width: "100%", height: "100%" }}
      attributionControl={{ compact: true }}
    >
      <NavigationControl position="top-right" />
      {children}
    </MapGL>
  );
}
