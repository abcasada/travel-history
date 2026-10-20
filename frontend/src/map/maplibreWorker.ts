/**
 * MapLibre builds its web-worker URL at runtime, which bundlers cannot follow, so the worker
 * would be missing from builds (and from Vite's dev pre-bundle). Bundle it explicitly and tell
 * MapLibre where it is. Imported once by BaseMap, before any map is created.
 */
import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

setWorkerUrl(workerUrl);
