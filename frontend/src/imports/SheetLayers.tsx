import type { ExpressionSpecification } from "maplibre-gl";
import { useEffect, useMemo } from "react";
import { Layer, Source, useMap } from "react-map-gl/maplibre";
import { useLocation, useSearchParams } from "react-router";
import { useGetImport, useGetTripSheetPreview } from "../api/generated";
import { MODE_COLORS } from "../trips/labels";
import { selectedImportId, selectedTab } from "./paths";
import { sheetBounds, sheetLegFeatures, sheetStopFeatures } from "./sheet";

const MODE_COLOR: ExpressionSpecification = [
  "match",
  ["get", "mode"],
  ...Object.entries(MODE_COLORS).flat(),
  MODE_COLORS.other,
] as unknown as ExpressionSpecification;

/**
 * The open spreadsheet preview's stops and legs (§28.8), drawn only on `/imports/:id`: every
 * tab, the one picked with "Show on map" (`?tab=`) highlighted, labelled and fitted. Lines are
 * straight (great-circle for flights): nothing is routed before the import.
 */
export function SheetLayers() {
  const { pathname } = useLocation();
  const batchId = selectedImportId(pathname);
  if (batchId === null) return null;
  return <SheetLayersInner batchId={batchId} />;
}

function SheetLayersInner({ batchId }: { batchId: number }) {
  const [params] = useSearchParams();
  const tab = selectedTab(params);
  // Shares the preview page's queries (same keys), so nothing is fetched twice.
  const batch = useGetImport(batchId);
  const hasPreview = ["preview", "done", "discarded"].includes(batch.data?.status ?? "");
  const preview = useGetTripSheetPreview(batchId, { query: { enabled: hasPreview } });
  const tabs = preview.data?.tabs;
  const legs = useMemo(() => sheetLegFeatures(tabs ?? []), [tabs]);
  const stops = useMemo(() => sheetStopFeatures(tabs ?? []), [tabs]);
  const focus = useMemo(() => {
    const picked = tabs?.filter((t) => t.record_id === tab);
    return sheetBounds(picked?.length ? picked : (tabs ?? []));
  }, [tabs, tab]);
  useFit(focus);
  if (!tabs) return null;

  const isOpen: ExpressionSpecification = ["==", ["get", "record_id"], tab ?? -1];
  const dim = tab !== null;
  return (
    <>
      <Source id="sheet-legs" type="geojson" data={legs}>
        <Layer
          id="sheet-legs"
          type="line"
          layout={{ "line-cap": "round", "line-join": "round" }}
          paint={{
            "line-color": MODE_COLOR,
            "line-width": ["case", isOpen, 4, 2.5],
            "line-opacity": dim ? ["case", isOpen, 0.95, 0.3] : 0.85,
            "line-dasharray": ["literal", [2, 1.5]],
          }}
        />
      </Source>
      <Source id="sheet-stops" type="geojson" data={stops}>
        <Layer
          id="sheet-stops"
          type="circle"
          paint={{
            "circle-radius": ["case", isOpen, 6, 4],
            "circle-color": "#ffffff",
            "circle-stroke-color": "#166534",
            "circle-stroke-width": 2,
            "circle-opacity": dim ? ["case", isOpen, 1, 0.4] : 1,
            "circle-stroke-opacity": dim ? ["case", isOpen, 1, 0.4] : 1,
          }}
        />
        <Layer
          id="sheet-stop-labels"
          type="symbol"
          filter={dim ? isOpen : ["literal", true]}
          layout={{
            "text-field": ["get", "name"],
            // A font the basemap's glyph server has (MapLibre's default isn't served there).
            "text-font": ["Noto Sans Regular"],
            "text-size": 12,
            "text-offset": [0, 1.1],
            "text-anchor": "top",
            "text-optional": true,
          }}
          paint={{ "text-color": "#1e293b", "text-halo-color": "#ffffff", "text-halo-width": 1.5 }}
        />
      </Source>
    </>
  );
}

/** Fit the map to the open tab (or the whole sheet) when that box changes. */
function useFit(bounds: ReturnType<typeof sheetBounds>) {
  const { current: ref } = useMap();
  const key = bounds ? bounds.flat().join(",") : null;
  // biome-ignore lint/correctness/useExhaustiveDependencies: refit only when the box changes
  useEffect(() => {
    const map = ref?.getMap();
    if (!map || !bounds) return;
    map.fitBounds(bounds, { padding: 60, maxZoom: 12, duration: 600 });
  }, [key, ref]);
}
