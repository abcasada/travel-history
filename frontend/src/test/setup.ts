import "@testing-library/jest-dom/vitest";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, vi } from "vitest";
import { installMatchMedia, setDesktopMedia } from "./media";

// MapLibre needs WebGL, which jsdom lacks; tests check everything around the map.
vi.mock("react-map-gl/maplibre", () => ({
  default: ({ children }: { children?: ReactNode }) =>
    createElement("div", { "data-testid": "basemap" }, children),
  NavigationControl: () => null,
  // Sources expose their tile URLs so tests can check what the map would request.
  Source: ({ id, tiles, children }: { id: string; tiles?: string[]; children?: ReactNode }) =>
    createElement(
      "div",
      { "data-testid": `source-${id}`, "data-tiles": tiles?.join(" ") },
      children,
    ),
  Layer: ({ id }: { id: string }) => createElement("div", { "data-testid": `layer-${id}` }),
  Popup: () => null,
  useMap: () => ({ current: undefined }),
}));

vi.mock("../map/maplibreWorker", () => ({}));

installMatchMedia();

// jsdom has no ResizeObserver (used by react-resizable-panels).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

beforeEach(() => {
  window.localStorage.clear();
  setDesktopMedia(true);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
