/** Runtime configuration. The basemap style URL is configuration so a self-hosted regional
 * PMTiles basemap can replace OpenFreeMap later without code changes (PLAN.md §14). */
export const config = {
  basemapStyle:
    import.meta.env.VITE_BASEMAP_STYLE ?? "https://tiles.openfreemap.org/styles/liberty",
  initialView: { longitude: -98.5, latitude: 39.5, zoom: 3.4 },
} as const;
