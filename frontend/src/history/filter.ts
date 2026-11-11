/**
 * The raw-history map's filter lives in the URL (`/history?from=2025-03-01&to=2025-03-31`), so
 * the list pane that edits it and the map that draws it share one source of truth, and a view
 * can be bookmarked. Days are local calendar days in the browser's time zone.
 */

export type HistoryFilter = {
  /** First local day shown (YYYY-MM-DD), inclusive. */
  from: string | null;
  /** Last local day shown (YYYY-MM-DD), inclusive. */
  to: string | null;
  /** Timeline segments overlay (on unless `segments=0`). */
  segments: boolean;
};

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function day(value: string | null): string | null {
  return value && DAY.test(value) && !Number.isNaN(parseDay(value).getTime()) ? value : null;
}

/** Local midnight at the start of a YYYY-MM-DD day. */
export function parseDay(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y ?? 0, (m ?? 1) - 1, d ?? 1);
}

export function formatDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(value: string, days: number): string {
  const date = parseDay(value);
  date.setDate(date.getDate() + days);
  return formatDay(date);
}

export function readFilter(params: URLSearchParams): HistoryFilter {
  let from = day(params.get("from"));
  let to = day(params.get("to"));
  if (from && to && to < from) [from, to] = [to, from];
  return { from, to, segments: params.get("segments") !== "0" };
}

/** Returns new search params with the filter applied (other params are kept). */
export function writeFilter(params: URLSearchParams, filter: HistoryFilter): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const [key, value] of [
    ["from", filter.from],
    ["to", filter.to],
  ] as const) {
    if (value) next.set(key, value);
    else next.delete(key);
  }
  if (filter.segments) next.delete("segments");
  else next.set("segments", "0");
  return next;
}

/** Query string for the tile endpoints: the local days as absolute instants [from, to+1). */
export function tileQuery(filter: HistoryFilter, revision = ""): string {
  const query = new URLSearchParams();
  if (filter.from) query.set("from", parseDay(filter.from).toISOString());
  if (filter.to) query.set("to", parseDay(addDays(filter.to, 1)).toISOString());
  // Tiles are browser-cached for a few minutes; a new import changes the URL instead.
  if (revision) query.set("rev", revision);
  const text = query.toString();
  return text ? `?${text}` : "";
}

export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}
