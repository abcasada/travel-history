/**
 * Local time in an IANA zone <-> UTC, without a date library. The API stores UTC instants plus
 * the zone name (CLAUDE.md "Times"); forms edit the local wall-clock time in that zone.
 */

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string): Intl.DateTimeFormat {
  let f = formatters.get(timeZone);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatters.set(timeZone, f);
  }
  return f;
}

function wallClock(utcMs: number, timeZone: string) {
  const parts: Record<string, number> = {};
  for (const p of formatter(timeZone).formatToParts(new Date(utcMs))) {
    if (p.type !== "literal") parts[p.type] = Number(p.value);
  }
  return parts as Record<"year" | "month" | "day" | "hour" | "minute" | "second", number>;
}

function offsetMs(utcMs: number, timeZone: string): number {
  const w = wallClock(utcMs, timeZone);
  const asUtc = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second);
  return asUtc - Math.floor(utcMs / 1000) * 1000;
}

export function browserZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function isValidZone(timeZone: string): boolean {
  if (!timeZone) return false;
  try {
    formatter(timeZone);
    return true;
  } catch {
    return false;
  }
}

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;

/** "2024-05-01T14:30" in `timeZone` -> ISO UTC instant. */
export function zonedToUtc(local: string, timeZone: string): string {
  const m = LOCAL.exec(local);
  if (!m) throw new Error(`not a local date-time: ${local}`);
  const [y = 0, mo = 1, d = 1, h = 0, mi = 0] = m.slice(1).map(Number);
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  // The offset at the guess may be the wrong side of a DST change; try both candidates. In a
  // repeated hour the first occurrence wins; in a skipped hour, the instant just after the gap.
  const a = guess - offsetMs(guess, timeZone);
  const b = guess - offsetMs(a, timeZone);
  const exact = [a, b].filter((t) => utcToZoned(new Date(t).toISOString(), timeZone) === local);
  const utc = exact.length ? Math.min(...exact) : Math.max(a, b);
  return new Date(utc).toISOString().replace(".000Z", "Z");
}

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO instant -> "2024-05-01T14:30" wall-clock time in `timeZone` (for datetime-local). */
export function utcToZoned(iso: string, timeZone: string): string {
  const w = wallClock(Date.parse(iso), timeZone);
  return `${w.year}-${pad(w.month)}-${pad(w.day)}T${pad(w.hour)}:${pad(w.minute)}`;
}

/** Human display of an instant in its own zone, e.g. "May 1, 2024, 2:30 PM CDT". */
export function formatInZone(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "";
  const zone = isValidZone(timeZone) ? timeZone : "UTC";
  // dateStyle/timeStyle can't be combined with timeZoneName, so the fields are spelled out.
  return new Date(iso).toLocaleString(undefined, {
    timeZone: zone,
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** "2024-05-01" -> "May 1, 2024" without shifting the day by the browser's zone. */
export function formatDate(date: string): string {
  const [y = 0, m = 1, d = 1] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    timeZone: "UTC",
    dateStyle: "medium",
  });
}

export function formatDateRange(start: string, end: string): string {
  return start === end ? formatDate(start) : `${formatDate(start)} – ${formatDate(end)}`;
}
