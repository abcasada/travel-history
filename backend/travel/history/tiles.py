"""Raw-history map data (PLAN.md §14, milestone 2.3): point and segment vector tiles, and the
per-day coverage strip.

Everything here is plain SQL run on the request's connection as `travel_app`, inside the
request's RLS transaction. None of it filters by owner: row-level security on
`history_locationpoint` / `history_timelinesegment` is what limits a tile to the caller's own
history, so a bug here cannot widen it. Callers check `policy.can_access_raw_history` first.

Bounds (so one request can't tie up the database or the browser):
- zoom 0..MAX_ZOOM only; x/y must lie inside the zoom level's grid;
- below POINTS_MIN_ZOOM, and above it whenever a tile holds more than MAX_POINTS_PER_TILE points,
  points are counted into a GRID x GRID grid per tile (one feature per occupied cell, so at most
  (GRID + 2*MARGIN_CELLS)^2 features however much history there is);
- segment tiles start at SEGMENTS_MIN_ZOOM and hold at most MAX_SEGMENTS_PER_TILE features
  (newest first), simplified to about a pixel;
- every tile query runs under a statement timeout (TileTimeout -> HTTP 503);
- the coverage strip covers at most MAX_COVERAGE_DAYS per request.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import psycopg.errors
from django.db import OperationalError, connection, transaction

MAX_ZOOM = 18
POINTS_MIN_ZOOM = 14
GRID_BITS = 7
GRID = 2**GRID_BITS  # cells per tile side when aggregating (4096 / 128 = 32 tile units per cell)
MARGIN_CELLS = 4  # neighbouring cells drawn too, so circles near tile edges aren't cut off
MAX_POINTS_PER_TILE = 10_000
SEGMENTS_MIN_ZOOM = 5
MAX_SEGMENTS_PER_TILE = 3_000
TIMEOUT_MS = 10_000
MAX_COVERAGE_DAYS = 400

EXTENT = 4096
BUFFER = EXTENT * MARGIN_CELLS // GRID  # tile units kept outside the tile edge (128)
MARGIN = MARGIN_CELLS / GRID  # the same margin as a fraction of the tile width


class TileError(ValueError):
    """Tile coordinates outside the supported range (HTTP 404)."""


class TileTimeout(Exception):
    """A tile query hit the statement timeout (HTTP 503; narrow the date range or zoom in)."""


@dataclass(frozen=True)
class Tile:
    data: bytes
    aggregated: bool
    truncated: bool = False


def check_tile(z: int, x: int, y: int, min_zoom: int = 0) -> None:
    if not (min_zoom <= z <= MAX_ZOOM):
        raise TileError(f"zoom must be between {min_zoom} and {MAX_ZOOM}")
    if not (0 <= x < 2**z and 0 <= y < 2**z):
        raise TileError("tile outside the grid")


# --- Point keys (history migration 0008) ----------------------------------------------------

KEY_ZOOM = 20  # app.tile_key(): the point's tile at this zoom, x/y bits interleaved
NEIGHBOUR_DEPTH = 2  # the margin is read from neighbours' adjacent quarter-tiles
KEY_CELLS_MAX_ZOOM = KEY_ZOOM - GRID_BITS  # up to here a grid cell is a key prefix


def _spread(v: int) -> int:
    out = 0
    for bit in range(KEY_ZOOM):
        out |= ((v >> bit) & 1) << (2 * bit)
    return out


def morton(x: int, y: int) -> int:
    """Same layout as app.tile_key(): y in the odd bits, x in the even bits."""
    return (_spread(y) << 1) | _spread(x)


def key_range(z: int, x: int, y: int) -> tuple[int, int]:
    """Every point inside tile z/x/y has lo <= tile_key < hi."""
    shift = 2 * (KEY_ZOOM - z)
    prefix = morton(x, y)
    return prefix << shift, (prefix + 1) << shift


def key_ranges(z: int, x: int, y: int) -> list[tuple[int, int]]:
    """Key ranges covering the tile plus its margin: the tile itself and, of each neighbour,
    the sub-tiles NEIGHBOUR_DEPTH levels down that touch it (a quarter of the neighbour, well
    beyond the 1/32-tile margin). No wrap-around at the antimeridian."""
    n, depth = 2**z, min(NEIGHBOUR_DEPTH, KEY_ZOOM - z)
    s = 2**depth
    ranges = [key_range(z, x, y)]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            nx, ny = x + dx, y + dy
            if (dx, dy) == (0, 0) or not (0 <= nx < n and 0 <= ny < n):
                continue
            columns = {-1: [s - 1], 0: range(s), 1: [0]}[dx]
            rows = {-1: [s - 1], 0: range(s), 1: [0]}[dy]
            ranges += [key_range(z + depth, nx * s + c, ny * s + r) for c in columns for r in rows]
    merged: list[tuple[int, int]] = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return merged


def _filters(
    alias: str,
    start: dt.datetime | None,
    end: dt.datetime | None,
    sources: Sequence[str] | None,
) -> tuple[str, dict]:
    """Time and source conditions on location points. Fixed SQL fragments, bound values."""
    sql, params = "", {}
    if start is not None:
        sql += f" AND {alias}.ts >= %(start)s"
        params["start"] = start
    if end is not None:
        sql += f" AND {alias}.ts < %(end)s"
        params["end"] = end
    if sources:
        sql += f" AND {alias}.source = ANY(%(sources)s)"
        params["sources"] = list(sources)
    return sql, params


# The tile, its envelope widened by the margin (in 4326 for the index lookup), and the grid.
# The queries below are composed only from these constants and the fixed fragments built in
# `_filters` / `segments_tile`; every value is a bound parameter (hence the S608 waivers).
_ENVELOPE = """
WITH q AS NOT MATERIALIZED (
  SELECT e.tile,
         ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s, margin => %(margin)s), 4326)
           AS outer4326,
         ST_XMin(e.tile) AS x0,
         ST_YMin(e.tile) AS y0,
         (ST_XMax(e.tile) - ST_XMin(e.tile)) / %(grid)s AS cell,
         (ST_XMax(e.tile) - ST_XMin(e.tile)) / %(extent)s AS px
    FROM (SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS tile) e
)
"""


def _point_join(ranges: list[tuple[int, int]], params: dict) -> str:
    """Points by key range (index on owner_id, tile_key), then the exact envelope check. The
    ranges are spelled out as constants rather than joined from an array: the planner then
    estimates them from the column statistics (an array join defaulted to a seq scan)."""
    keys = _key_condition(ranges, params)
    return f"JOIN history_locationpoint p ON {keys} AND p.geom && q.outer4326"


def _key_condition(ranges: list[tuple[int, int]], params: dict) -> str:
    terms = []
    for i, (lo, hi) in enumerate(ranges):
        params[f"lo{i}"], params[f"hi{i}"] = lo, hi
        terms.append(f"(p.tile_key >= %(lo{i})s AND p.tile_key < %(hi{i})s)")
    return "(" + " OR ".join(terms) + ")"


_COUNT_POINTS = (
    _ENVELOPE  # noqa: S608
    + """
SELECT count(*) FROM (
  SELECT 1 FROM q {points}
   WHERE true {filters}
   LIMIT %(cap)s
) s
"""
)

_POINTS = (
    _ENVELOPE  # noqa: S608
    + """
SELECT ST_AsMVT(f, 'points', %(extent)s, 'geom') FROM (
  SELECT ST_AsMVTGeom(ST_Transform(p.geom, 3857), q.tile, %(extent)s, %(buffer)s, true) AS geom,
         1 AS n,
         extract(epoch FROM p.ts)::bigint AS ts,
         p.source AS src
    FROM q {points}
   WHERE true {filters}
) f
"""
)

# Cells are aligned to the tile corner and the cell size divides the tile width, so every tile
# at a zoom level shares one global grid: a cell in the margin is the same cell (and count) its
# neighbouring tile draws.
_CELLS = (
    _ENVELOPE  # noqa: S608
    + """
, cells AS (
  SELECT floor((m.mx - q.x0) / q.cell) AS cx,
         floor((m.my - q.y0) / q.cell) AS cy,
         count(*) AS n
    FROM q {points}
    -- Web Mercator by hand: plain arithmetic is several times cheaper per point than
    -- ST_Transform, and the cell only needs to be right to a fraction of a pixel.
    CROSS JOIN LATERAL (
      SELECT 6378137 * radians(ST_X(p.geom)) AS mx,
             6378137 * ln(tan(pi() / 4 + radians(
               least(greatest(ST_Y(p.geom), -85.0511287798), 85.0511287798)) / 2)) AS my
    ) m
   WHERE true {filters}
   GROUP BY 1, 2
)
SELECT ST_AsMVT(f, 'points', %(extent)s, 'geom') FROM (
  SELECT ST_AsMVTGeom(
           ST_Point(q.x0 + (c.cx + 0.5) * q.cell, q.y0 + (c.cy + 0.5) * q.cell, 3857),
           q.tile, %(extent)s, %(buffer)s, true) AS geom,
         c.n
    FROM cells c, q
) f
-- A cell a rounding error beyond the margin is clipped to NULL by ST_AsMVTGeom (and skipped).
"""
)

# Below POINTS_MIN_ZOOM a grid cell (1/GRID of the tile) is exactly the tile GRID_BITS zoom
# levels further down, so points are grouped by their key's leading bits: integer work straight
# off the (owner_id, tile_key) index, without touching the geometry. Same cells as _CELLS.
_KEY_CELLS = (
    _ENVELOPE  # noqa: S608
    + """
, cells AS (
  SELECT p.tile_key >> %(shift)s AS c, count(*) AS n
    FROM history_locationpoint p
   WHERE {keys} {filters}
   GROUP BY 1
)
SELECT ST_AsMVT(f, 'points', %(extent)s, 'geom') FROM (
  SELECT ST_AsMVTGeom(
           ST_Point(-20037508.342789244 + (app.morton_compact(c.c) + 0.5) * q.cell,
                    20037508.342789244 - (app.morton_compact(c.c >> 1) + 0.5) * q.cell, 3857),
           q.tile, %(extent)s, %(buffer)s, true) AS geom,
         c.n
    FROM cells c, q
) f
"""
)

_SEGMENTS = (
    _ENVELOPE  # noqa: S608
    + """
, picked AS (
  SELECT s.id, s.kind, s.activity_type, s.semantic_type, s.start_utc, s.end_utc,
         ST_Transform(s.geom, 3857) AS g
    FROM q JOIN history_timelinesegment s ON s.geom && q.outer4326
   WHERE s.is_current {filters}
   ORDER BY s.start_utc DESC
   LIMIT %(cap)s
)
SELECT ST_AsMVT(f, 'segments', %(extent)s, 'geom'), (SELECT count(*) FROM picked) FROM (
  SELECT ST_AsMVTGeom(ST_Simplify(p.g, q.px), q.tile, %(extent)s, %(buffer)s, true) AS geom,
         p.id,
         p.kind,
         p.activity_type AS activity,
         p.semantic_type AS semantic,
         extract(epoch FROM p.start_utc)::bigint AS t0,
         extract(epoch FROM p.end_utc)::bigint AS t1
    FROM picked p, q
) f
WHERE f.geom IS NOT NULL
"""
)


def _run(sql: str, params: dict, *, many: bool = False):
    """One bounded query in a savepoint: a timeout rolls back only the savepoint, so the
    request's transaction (and its RLS context) stays usable. JIT is off: these queries are
    short, and compiling them cost more (~0.5-1 s) than it ever saved."""
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('statement_timeout'), current_setting('jit')")
            previous = cursor.fetchone()
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true), set_config('jit', 'off', true)",
                [str(TIMEOUT_MS)],
            )
            cursor.execute(sql, params)
            result = cursor.fetchall() if many else cursor.fetchone()
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true), set_config('jit', %s, true)",
                list(previous),
            )
            return result
    except OperationalError as error:
        if isinstance(error.__cause__, psycopg.errors.QueryCanceled):
            raise TileTimeout from error
        raise


def _base_params(z: int, x: int, y: int) -> dict:
    return {
        "z": z,
        "x": x,
        "y": y,
        "margin": MARGIN,
        "grid": GRID,
        "extent": EXTENT,
        "buffer": BUFFER,
    }


def points_tile(
    z: int,
    x: int,
    y: int,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    sources: Sequence[str] | None = None,
) -> Tile:
    """The caller's location points in one tile: single points (n=1, ts, src) when zoomed in
    and sparse enough, otherwise grid cells (n = number of points in the cell)."""
    check_tile(z, x, y)
    filters, params = _filters("p", start, end, sources)
    params |= _base_params(z, x, y)
    ranges = key_ranges(z, x, y)
    sql = {"filters": filters, "points": _point_join(ranges, params)}
    if z >= POINTS_MIN_ZOOM:
        params["cap"] = MAX_POINTS_PER_TILE + 1
        (count,) = _run(_COUNT_POINTS.format(**sql), params)
        if count <= MAX_POINTS_PER_TILE:
            (data,) = _run(_POINTS.format(**sql), params)
            return Tile(bytes(data or b""), aggregated=False)
    if z <= KEY_CELLS_MAX_ZOOM:
        params["shift"] = 2 * (KEY_ZOOM - z - GRID_BITS)
        sql["keys"] = _key_condition(ranges, params)
        (data,) = _run(_KEY_CELLS.format(**sql), params)
    else:  # a dense tile at zoom 14+: cells finer than the key's resolution
        (data,) = _run(_CELLS.format(**sql), params)
    return Tile(bytes(data or b""), aggregated=True)


def segments_tile(
    z: int,
    x: int,
    y: int,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> Tile:
    """The caller's current Timeline segments (visits as points, activities and paths as lines)
    overlapping [start, end)."""
    check_tile(z, x, y, min_zoom=SEGMENTS_MIN_ZOOM)
    filters, params = "", _base_params(z, x, y)
    if start is not None:
        filters += " AND s.end_utc >= %(start)s"
        params["start"] = start
    if end is not None:
        filters += " AND s.start_utc < %(end)s"
        params["end"] = end
    params["cap"] = MAX_SEGMENTS_PER_TILE
    data, picked = _run(_SEGMENTS.format(filters=filters), params)
    return Tile(bytes(data or b""), aggregated=False, truncated=picked >= MAX_SEGMENTS_PER_TILE)


# --- Coverage strip ------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageDay:
    day: dt.date
    points: int
    segments: int


@dataclass(frozen=True)
class Coverage:
    first_day: dt.date | None
    last_day: dt.date | None
    days: list[CoverageDay]


def local_midnight(day: dt.date, zone: ZoneInfo) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(), tzinfo=zone)


def coverage(first: dt.date, last: dt.date, zone: ZoneInfo) -> Coverage:
    """Per local day in [first, last]: how many points and current segments the caller has.
    Days without data are left out. Also the caller's overall first and last day with data.
    Raises TileTimeout like the tiles do."""
    if last < first:
        raise ValueError("'to' is before 'from'")
    if (last - first).days + 1 > MAX_COVERAGE_DAYS:
        raise ValueError(f"at most {MAX_COVERAGE_DAYS} days per request")
    params = {
        "tz": zone.key,
        "start": local_midnight(first, zone),
        "end": local_midnight(last + dt.timedelta(days=1), zone),
    }
    lo, hi = _run(
        """
        SELECT least((SELECT min(ts) FROM history_locationpoint),
                     (SELECT min(start_utc) FROM history_timelinesegment WHERE is_current)),
               greatest((SELECT max(ts) FROM history_locationpoint),
                        (SELECT max(end_utc) FROM history_timelinesegment WHERE is_current))
        """,
        {},
    )
    points = dict(
        _run(
            """
            SELECT (p.ts AT TIME ZONE %(tz)s)::date, count(*)
              FROM history_locationpoint p
             WHERE p.ts >= %(start)s AND p.ts < %(end)s
             GROUP BY 1
            """,
            params,
            many=True,
        )
    )
    # A segment counts on every local day it touches (an overnight stay covers two days).
    segments = dict(
        _run(
            """
            SELECT d::date, count(*)
              FROM history_timelinesegment s
             CROSS JOIN LATERAL generate_series(
                     date_trunc('day', greatest(s.start_utc, %(start)s) AT TIME ZONE %(tz)s),
                     date_trunc('day', least(s.end_utc, %(end)s - interval '1 microsecond')
                                         AT TIME ZONE %(tz)s),
                     interval '1 day') d
             WHERE s.is_current AND s.end_utc >= %(start)s AND s.start_utc < %(end)s
             GROUP BY 1
            """,
            params,
            many=True,
        )
    )
    days = [
        CoverageDay(day=day, points=points.get(day, 0), segments=segments.get(day, 0))
        for day in sorted(points.keys() | segments.keys())
    ]
    return Coverage(
        first_day=lo.astimezone(zone).date() if lo else None,
        last_day=hi.astimezone(zone).date() if hi else None,
        days=days,
    )
