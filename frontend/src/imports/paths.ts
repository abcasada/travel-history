/** URL builders for the imports pages (trip spreadsheets, docs/design/trip-sheet.md §28.8). */
import { matchPath } from "react-router";

export const importPaths = {
  list: "/imports",
  /** A batch's preview; `tab` (a record id) is the tab the map highlights and fits. */
  batch: (batchId: number, tab?: number) =>
    tab === undefined ? `/imports/${batchId}` : `/imports/${batchId}?tab=${tab}`,
};

/** The batch whose preview is open (`/imports/12`), else null. */
export function selectedImportId(pathname: string): number | null {
  const match = matchPath({ path: "/imports/:batchId" }, pathname);
  const id = Number(match?.params.batchId);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** The tab the preview has open (`?tab=<record id>`), else null. */
export function selectedTab(params: URLSearchParams): number | null {
  const id = Number(params.get("tab"));
  return Number.isInteger(id) && id > 0 ? id : null;
}
