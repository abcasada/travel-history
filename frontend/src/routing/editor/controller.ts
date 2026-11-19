/*
 * The drag editor's map side (docs/design/routing.md §13.4): draws the line and its anchors on
 * the MapLibre map and turns mouse gestures into editor actions. Framework-free; RouteEditorLayer
 * attaches it to the shared map.
 *
 * Ported to TypeScript from gpx.studio (https://github.com/gpxstudio/gpx.studio, commit 2e0edc7,
 * 2026-11-15), website/src/lib/components/toolbar/tools/routing/routing-controls.ts: one GeoJSON
 * source for all anchors filtered by zoom, dragging an anchor (pan disabled while dragging,
 * the feature moved with updateData), the temporary anchor that follows the pointer along the
 * line and can be dragged or clicked, shift-click to delete, click on the map to append. Changes:
 * no popup (right-click also deletes), no touch handling (the editor is desktop-only), no
 * Svelte stores or engine commands: actions go to the editor store.
 *
 * MIT License
 *
 * Copyright (c) 2026 gpx.studio
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

import type {
  GeoJSONSource,
  MapLayerMouseEvent,
  Map as MapLibreMap,
  MapMouseEvent,
  Point,
} from "maplibre-gl";
import type { Coord } from "./geometry";
import { type Anchor, anchors as anchorsOf, type EditorState } from "./model";

export const LINE_ID = "route-editor-line";
export const LINE_HIT_ID = "route-editor-line-hit";
export const ANCHORS_ID = "route-editor-anchors";

export type EditorActions = {
  move: (index: number, to: Coord, zoom: number) => void;
  dragLine: (grabbed: Coord, to: Coord, zoom: number) => void;
  append: (to: Coord) => void;
  remove: (index: number, zoom: number) => void;
  insert: (at: Coord) => void;
  /** True while a route request is out, or while another map tool owns the clicks. */
  blocked: () => boolean;
};

type AnchorProperties = { anchorIndex: number; minZoom: number };

const lngLat = (e: MapMouseEvent): Coord => [e.lngLat.lng, e.lngLat.lat];

export class RouteEditorController {
  private anchors: Anchor[] = [];
  private state: EditorState | null = null;
  /** Id of the dragged anchor feature: `anchors.length` for the temporary anchor. */
  private draggedAnchorId: number | null = null;
  private lastDragTime = 0;
  private dragStart: Point | null = null;
  /** Where the pointer hovers the line: an anchor that can be dragged or clicked to be added. */
  private temporaryAnchor: Coord | null = null;

  constructor(
    private readonly map: MapLibreMap,
    private readonly actions: EditorActions,
  ) {
    this.map.on("style.load", this.addLayers);
    this.addLayers();
    this.map.on("click", this.onClick);
    this.map.on("contextmenu", ANCHORS_ID, this.onContextMenu);
    this.map.on("mousedown", ANCHORS_ID, this.onMouseDown);
    this.map.on("mouseenter", ANCHORS_ID, this.onMouseEnter);
    this.map.on("mouseleave", ANCHORS_ID, this.onMouseLeave);
    this.map.on("mousemove", LINE_HIT_ID, this.showTemporaryAnchor);
  }

  destroy() {
    this.map.off("style.load", this.addLayers);
    this.map.off("click", this.onClick);
    this.map.off("contextmenu", ANCHORS_ID, this.onContextMenu);
    this.map.off("mousedown", ANCHORS_ID, this.onMouseDown);
    this.map.off("mouseenter", ANCHORS_ID, this.onMouseEnter);
    this.map.off("mouseleave", ANCHORS_ID, this.onMouseLeave);
    this.map.off("mousemove", LINE_HIT_ID, this.showTemporaryAnchor);
    this.map.off("mousemove", this.updateTemporaryAnchor);
    this.map.off("mousemove", this.onMouseMove);
    this.map.dragPan.enable();
    this.map.getCanvas().style.cursor = "";
    try {
      for (const id of [ANCHORS_ID, LINE_ID, LINE_HIT_ID]) {
        if (this.map.getLayer(id)) this.map.removeLayer(id);
      }
      for (const id of [ANCHORS_ID, LINE_ID]) {
        if (this.map.getSource(id)) this.map.removeSource(id);
      }
    } catch {
      // The map may already be gone (page left).
    }
  }

  /** Redraws the line and the anchors from the editor state. */
  render(state: EditorState) {
    this.state = state;
    this.anchors = anchorsOf(state);
    // the anchors have changed, so has what is hovered
    this.temporaryAnchor = null;
    this.map.off("mousemove", this.updateTemporaryAnchor);
    this.lineSource()?.setData(this.lineData());
    this.anchorSource()?.setData(this.anchorData());
  }

  private lineSource() {
    return this.map.getSource(LINE_ID) as GeoJSONSource | undefined;
  }

  private anchorSource() {
    return this.map.getSource(ANCHORS_ID) as GeoJSONSource | undefined;
  }

  private lineData(): GeoJSON.FeatureCollection {
    const coordinates = (this.state?.points ?? []).map((p) => [p.lon, p.lat]);
    return {
      type: "FeatureCollection",
      features:
        coordinates.length > 1
          ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates } }]
          : [],
    };
  }

  private anchorData(): GeoJSON.FeatureCollection<GeoJSON.Point, AnchorProperties> {
    return {
      type: "FeatureCollection",
      features: this.anchors.map((anchor, id) => ({
        type: "Feature",
        id,
        geometry: { type: "Point", coordinates: [anchor.lon, anchor.lat] },
        properties: { anchorIndex: id, minZoom: anchor.zoom },
      })),
    };
  }

  private addLayers = () => {
    // No reliable way to check that the style can take sources yet; a later style.load retries.
    try {
      if (!this.map.getSource(LINE_ID)) {
        this.map.addSource(LINE_ID, { type: "geojson", data: this.lineData() });
      }
      if (!this.map.getSource(ANCHORS_ID)) {
        this.map.addSource(ANCHORS_ID, {
          type: "geojson",
          data: this.anchorData(),
          promoteId: "anchorIndex",
        });
      }
      if (!this.map.getLayer(LINE_ID)) {
        this.map.addLayer({
          id: LINE_ID,
          type: "line",
          source: LINE_ID,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#2563eb", "line-width": 5, "line-opacity": 0.9 },
        });
      }
      if (!this.map.getLayer(LINE_HIT_ID)) {
        // A wide invisible line, so the pointer finds the route without pixel precision.
        this.map.addLayer({
          id: LINE_HIT_ID,
          type: "line",
          source: LINE_ID,
          paint: { "line-color": "#000000", "line-width": 16, "line-opacity": 0 },
        });
      }
      if (!this.map.getLayer(ANCHORS_ID)) {
        this.map.addLayer({
          id: ANCHORS_ID,
          type: "circle",
          source: ANCHORS_ID,
          paint: {
            "circle-radius": 6,
            "circle-color": "#ffffff",
            "circle-stroke-width": 2,
            "circle-stroke-color": "#1e293b",
          },
          filter: [">=", ["zoom"], ["get", "minZoom"]],
        });
      }
    } catch {
      // retried on style.load
    }
  };

  private justDragged() {
    return this.draggedAnchorId !== null || Date.now() - this.lastDragTime < 100;
  }

  private onClick = (e: MapMouseEvent) => {
    if (this.justDragged() || this.actions.blocked()) return;
    const layers = [ANCHORS_ID, LINE_HIT_ID].filter((id) => this.map.getLayer(id));
    const hits = layers.length ? this.map.queryRenderedFeatures(e.point, { layers }) : [];
    const anchorHit = hits.find((f) => f.layer.id === ANCHORS_ID);
    if (anchorHit) {
      const anchor = this.anchors[Number(anchorHit.properties?.anchorIndex)];
      if (!anchor) {
        // the temporary anchor on the line: a click on it adds it
        if (this.temporaryAnchor) this.actions.insert(this.temporaryAnchor);
        this.removeTemporaryAnchor();
      } else if (e.originalEvent.shiftKey) {
        this.actions.remove(anchor.index, this.map.getZoom());
      }
      return;
    }
    if (hits.some((f) => f.layer.id === LINE_HIT_ID)) {
      this.actions.insert(lngLat(e));
      return;
    }
    this.actions.append(lngLat(e));
  };

  private onContextMenu = (e: MapLayerMouseEvent) => {
    e.preventDefault();
    if (this.actions.blocked()) return;
    const anchor = this.anchors[Number(e.features?.[0]?.properties?.anchorIndex)];
    if (anchor) this.actions.remove(anchor.index, this.map.getZoom());
  };

  private onMouseEnter = () => {
    this.map.getCanvas().style.cursor = "grab";
  };

  private onMouseLeave = () => {
    if (this.temporaryAnchor === null && this.draggedAnchorId === null) {
      this.map.getCanvas().style.cursor = "";
    }
  };

  private onMouseDown = (e: MapLayerMouseEvent) => {
    if (e.originalEvent.button !== 0 || this.actions.blocked()) return;
    e.preventDefault();
    this.map.dragPan.disable();
    this.draggedAnchorId = Number(e.features?.[0]?.properties?.anchorIndex);
    this.dragStart = e.point;
    this.map.on("mousemove", this.onMouseMove);
    this.map.once("mouseup", this.onMouseUp);
  };

  private onMouseMove = (e: MapMouseEvent) => {
    if (this.draggedAnchorId === null || (this.dragStart && e.point.equals(this.dragStart))) {
      return;
    }
    this.map.getCanvas().style.cursor = "grabbing";
    this.moveAnchorFeature(this.draggedAnchorId, lngLat(e));
    this.lastDragTime = Date.now();
  };

  private onMouseUp = (e: MapMouseEvent) => {
    this.map.dragPan.enable();
    this.map.off("mousemove", this.onMouseMove);
    this.map.getCanvas().style.cursor = "";
    const id = this.draggedAnchorId;
    this.draggedAnchorId = null;
    if (id === null || (this.dragStart && e.point.equals(this.dragStart))) return;
    this.lastDragTime = Date.now();
    const zoom = this.map.getZoom();
    if (id === this.anchors.length && this.temporaryAnchor) {
      const grabbed = this.temporaryAnchor;
      this.removeTemporaryAnchor();
      this.actions.dragLine(grabbed, lngLat(e), zoom);
    } else if (this.anchors[id]) {
      this.actions.move(this.anchors[id].index, lngLat(e), zoom);
    }
  };

  private showTemporaryAnchor = (e: MapLayerMouseEvent) => {
    if (this.draggedAnchorId !== null || this.actions.blocked()) return;
    if (this.closeToAnAnchor(e.point)) return;
    const first = this.temporaryAnchor === null;
    this.temporaryAnchor = lngLat(e);
    if (first) {
      this.anchorSource()?.updateData({
        add: [
          {
            type: "Feature",
            id: this.anchors.length,
            geometry: { type: "Point", coordinates: [...this.temporaryAnchor] },
            properties: { anchorIndex: this.anchors.length, minZoom: 0 },
          },
        ],
      });
      this.map.on("mousemove", this.updateTemporaryAnchor);
    } else {
      this.moveAnchorFeature(this.anchors.length, this.temporaryAnchor);
    }
    this.map.getCanvas().style.cursor = "grab";
  };

  private updateTemporaryAnchor = (e: MapMouseEvent) => {
    if (!this.temporaryAnchor) return;
    if (this.draggedAnchorId !== null) {
      // being dragged: stop following the pointer along the line
      this.map.off("mousemove", this.updateTemporaryAnchor);
      return;
    }
    const at = this.map.project(this.temporaryAnchor as [number, number]);
    if (e.point.dist(at) > 20 || this.closeToAnAnchor(e.point)) this.removeTemporaryAnchor();
  };

  private closeToAnAnchor(point: Point): boolean {
    const zoom = this.map.getZoom();
    return this.anchors.some(
      (a) => zoom >= a.zoom && point.dist(this.map.project([a.lon, a.lat])) < 10,
    );
  }

  private moveAnchorFeature(id: number, to: Coord) {
    this.anchorSource()?.updateData({
      update: [{ id, newGeometry: { type: "Point", coordinates: [...to] } }],
    });
  }

  private removeTemporaryAnchor() {
    if (!this.temporaryAnchor) return;
    this.anchorSource()?.updateData({ remove: [this.anchors.length] });
    this.map.off("mousemove", this.updateTemporaryAnchor);
    this.map.getCanvas().style.cursor = "";
    this.temporaryAnchor = null;
  }
}
