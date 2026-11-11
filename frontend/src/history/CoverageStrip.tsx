import { useEffect, useState } from "react";
import { type CoverageDayOut, useGetHistoryCoverage } from "../api/generated";
import { browserTimeZone, formatDay } from "./filter";

const CELL = 10;
const GAP = 2;
const STEP = CELL + GAP;
const TOP = 12; // room for month labels
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Fill for a day: none, Timeline segments only, or points in four log-scale shades. */
export function shade(day: CoverageDayOut | undefined): string {
  if (!day || (day.points === 0 && day.segments === 0)) return "#e2e8f0";
  if (day.points === 0) return "#99f6e4";
  if (day.points < 10) return "#bfdbfe";
  if (day.points < 100) return "#60a5fa";
  if (day.points < 1000) return "#2563eb";
  return "#1e3a8a";
}

function daysOf(year: number): Date[] {
  const out: Date[] = [];
  for (let d = new Date(year, 0, 1); d.getFullYear() === year; d.setDate(d.getDate() + 1)) {
    out.push(new Date(d));
  }
  return out;
}

type Props = {
  from: string | null;
  to: string | null;
  /** A day was clicked; `extend` (shift-click) asks to stretch the current range to it. */
  onPick: (day: string, extend: boolean) => void;
};

/** One year of days, a column per week: which days have raw history (PLAN.md milestone 2.3).
 * Click a day to show only that day on the map; shift-click to extend the range. */
export function CoverageStrip({ from, to, onPick }: Props) {
  const [year, setYear] = useState<number | null>(from ? Number(from.slice(0, 4)) : null);
  const shownYear = year ?? new Date().getFullYear();
  const coverage = useGetHistoryCoverage({
    from: `${shownYear}-01-01`,
    to: `${shownYear}-12-31`,
    tz: browserTimeZone(),
  });
  const data = coverage.data;
  const firstYear = data?.first_day ? Number(data.first_day.slice(0, 4)) : shownYear;
  const lastYear = data?.last_day ? Number(data.last_day.slice(0, 4)) : shownYear;

  // Nothing chosen yet and this year is empty: jump to the latest year that has history.
  useEffect(() => {
    if (year === null && data && data.days.length === 0 && data.last_day) {
      setYear(Number(data.last_day.slice(0, 4)));
    }
  }, [year, data]);

  const byDay = new Map((data?.days ?? []).map((d) => [d.day, d]));
  const days = daysOf(shownYear);
  const offset = days[0]?.getDay() ?? 0;
  const weeks = Math.ceil((days.length + offset) / 7);
  const total = (data?.days ?? []).reduce(
    (n, d) => n + (d.points > 0 || d.segments > 0 ? 1 : 0),
    0,
  );

  return (
    <div>
      <div className="mb-1 flex items-center gap-2 text-sm">
        <button
          type="button"
          className="rounded px-2 hover:bg-slate-100 disabled:opacity-30"
          onClick={() => setYear(shownYear - 1)}
          disabled={shownYear <= firstYear}
          aria-label="Previous year"
        >
          ‹
        </button>
        <span className="font-medium">{shownYear}</span>
        <button
          type="button"
          className="rounded px-2 hover:bg-slate-100 disabled:opacity-30"
          onClick={() => setYear(shownYear + 1)}
          disabled={shownYear >= Math.max(lastYear, new Date().getFullYear())}
          aria-label="Next year"
        >
          ›
        </button>
        <span className="text-slate-500">
          {coverage.isLoading ? "Loading…" : `${total} day${total === 1 ? "" : "s"} with data`}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${weeks * STEP} ${TOP + 7 * STEP}`}
        className="w-full max-w-[42rem]"
        role="img"
        aria-label={`Days with location history in ${shownYear}`}
      >
        {MONTHS.map((label, month) => {
          const first = new Date(shownYear, month, 1);
          const index = Math.round((first.getTime() - new Date(shownYear, 0, 1).getTime()) / 864e5);
          return (
            <text
              key={label}
              x={Math.floor((index + offset) / 7) * STEP}
              y={9}
              fontSize={8}
              fill="#64748b"
            >
              {label}
            </text>
          );
        })}
        {days.map((date, index) => {
          const key = formatDay(date);
          const info = byDay.get(key);
          const selected = from !== null && key >= from && key <= (to ?? from);
          return (
            // biome-ignore lint/a11y/noStaticElementInteractions: the date inputs are the keyboard path
            <rect
              key={key}
              data-day={key}
              x={Math.floor((index + offset) / 7) * STEP}
              y={TOP + date.getDay() * STEP}
              width={CELL}
              height={CELL}
              rx={2}
              fill={shade(info)}
              stroke={selected ? "#f97316" : "none"}
              strokeWidth={selected ? 2 : 0}
              className="cursor-pointer"
              onClick={(event) => onPick(key, event.shiftKey)}
            >
              <title>
                {key}: {info ? `${info.points} points, ${info.segments} segments` : "no data"}
              </title>
            </rect>
          );
        })}
      </svg>
      <p className="mt-1 flex flex-wrap gap-3 text-xs text-slate-600">
        <Legend color={shade(undefined)} label="none" />
        <Legend color={shade({ day: "", points: 0, segments: 1 })} label="Timeline visits only" />
        <Legend color={shade({ day: "", points: 50, segments: 0 })} label="points" />
        <span>Click a day to show it; shift-click to extend.</span>
      </p>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}
