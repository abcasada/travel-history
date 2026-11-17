"""Raw-history map data (PLAN.md §14, milestone 2.3): point and segment vector tiles, and the
per-day coverage strip.

Everything here is plain SQL run on the request's connection as `travel_app`, inside the
request's RLS transaction. None of it filters by owner: row-level security on
`history_locationpoint` / `history_timelinesegment` is what limits a tile to the caller's own
history, so a bug here cannot widen it. Callers check `policy.can_access_raw_history` first.

Bounds (so one request can't tie up the database or the browser):
- zoom 0..MAX_ZOOM only; x/y must lie inside the zoom level's grid;
- below POINTS_MIN_ZOOM, and above it whenever a tile holds more than MAX_POINTS_PER_TILE points,
  points are counted into a grid of at most GRID x GRID cells per tile (one feature per occupied
  cell, so at most (GRID + 2*MARGIN_CELLS)^2 features however much history there is). The counts
  come from the per-day/per-year roll-up (`history_pointrollup`, history migration 0010), with raw
  points only for the partial UTC days at the ends of a date range;
- segment tiles start at SEGMENTS_MIN_ZOOM; up to MAX_SEGMENTS_PER_TILE segments are drawn one
  feature each, simplified to about a pixel; denser tiles snap geometries to a coarse lattice and
  merge the ones that coincide (at most MAX_SEGMENT_FEATURES features, most travelled first);
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
MAX_SEGMENTS_PER_TILE = 3_000  # beyond this, identical-looking segments are merged
SEGMENT_LATTICE = 64  # merged geometries snap to a 64 x 64 lattice per tile (4 px at 256 px)
MAX_SEGMENT_FEATURES = 10_000
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

# The roll-up's cell zooms and grains (history migration 0010 must list the same).
ROLLUP_LEVELS = (8, 10, 12, 14, 16, 18, 20)
GRAIN_DAY, GRAIN_YEAR = 1, 2
USE_ROLLUP = True  # tests switch it off to compare against counting raw points


def _spread(v: int) -> int:
    """The 20 low bits of v moved to the even bit positions (as in app.tile_key())."""
    v &= 0xFFFFF
    v = (v | (v << 16)) & 0x0000FFFF0000FFFF
    v = (v | (v << 8)) & 0x00FF00FF00FF00FF
    v = (v | (v << 4)) & 0x0F0F0F0F0F0F0F0F
    v = (v | (v << 2)) & 0x3333333333333333
    return (v | (v << 1)) & 0x5555555555555555


def morton(x: int, y: int) -> int:
    """Same layout as app.tile_key(): y in the odd bits, x in the even bits."""
    return (_spread(y) << 1) | _spread(x)


def key_range(z: int, x: int, y: int) -> tuple[int, int]:
    """Every point inside tile z/x/y has lo <= tile_key < hi."""
    shift = 2 * (KEY_ZOOM - z)
    prefix = morton(x, y)
    return prefix << shift, (prefix + 1) << shift


def _pieces(z: int, x: int, y: int) -> list[tuple[int, int, int]]:
    """The tile itself and, of each neighbour, the sub-tiles NEIGHBOUR_DEPTH levels down that
    touch it (a quarter of the neighbour, well beyond the 1/32-tile margin), as (z, x, y).
    No wrap-around at the antimeridian."""
    n, depth = 2**z, min(NEIGHBOUR_DEPTH, KEY_ZOOM - z)
    s = 2**depth
    pieces = [(z, x, y)]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            nx, ny = x + dx, y + dy
            if (dx, dy) == (0, 0) or not (0 <= nx < n and 0 <= ny < n):
                continue
            columns = {-1: [s - 1], 0: range(s), 1: [0]}[dx]
            rows = {-1: [s - 1], 0: range(s), 1: [0]}[dy]
            pieces += [(z + depth, nx * s + c, ny * s + r) for c in columns for r in rows]
    return pieces


def key_ranges(z: int, x: int, y: int) -> list[tuple[int, int]]:
    """Key ranges covering the tile plus its margin (`_pieces`), merged."""
    merged: list[tuple[int, int]] = []
    for lo, hi in sorted(key_range(*piece) for piece in _pieces(z, x, y)):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return merged


SEG_ZOOM_BITS = 5  # app.extent_key(): (zoom-20 Morton prefix) << 5 | zoom


def segment_key(z: int, x: int, y: int) -> int:
    """app.extent_key() of a geometry whose smallest enclosing tile is z/x/y."""
    return (key_range(z, x, y)[0] << SEG_ZOOM_BITS) | z


def segment_keys(z: int, x: int, y: int) -> tuple[list[tuple[int, int]], list[int]]:
    """What a segment's key must match to touch tile z/x/y or its margin: a key range for
    segments whose enclosing tile lies inside a piece (`key_ranges`, shifted), or one of the
    pieces' ancestors' keys (segments whose enclosing tile holds a piece). Quadtree tiles are
    nested or disjoint, so nothing else can overlap."""
    ranges = [(lo << SEG_ZOOM_BITS, hi << SEG_ZOOM_BITS) for lo, hi in key_ranges(z, x, y)]
    ancestors = {
        segment_key(k, px >> (pz - k), py >> (pz - k))
        for pz, px, py in _pieces(z, x, y)
        for k in range(pz)
    }
    outside = sorted(key for key in ancestors if not any(lo <= key < hi for lo, hi in ranges))
    return ranges, outside


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


def _key_condition(
    ranges: list[tuple[int, int]], params: dict, column: str = "p.tile_key", shift: int = 0
) -> str:
    """`column` inside any of the key ranges, cut by `shift` bits (the ranges are aligned to a
    zoom at or below the column's, so the cut is exact). Bound values, one name per range."""
    terms = []
    for lo, hi in ranges:
        i = len(params)
        params[f"k{i}"], params[f"k{i + 1}"] = lo >> shift, hi >> shift
        terms.append(f"({column} >= %(k{i})s AND {column} < %(k{i + 1})s)")
    return "(" + " OR ".join(terms) + ")"


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

# Grid cells are map tiles further down (at most zoom KEY_ZOOM), so a cell is a key prefix:
# counts are summed by prefix from the roll-up (and raw points' keys), without touching geometry.
# Cells form one global grid per zoom level, so a cell in a tile's margin is the same cell (and
# count) the neighbouring tile draws. Only the tile's own cells (one key prefix) and the margin
# cells listed by `_margin_cells` are placed - straight in tile coordinates, which is what
# ST_AsMVT takes - so the neighbours' wider key ranges cost no geometry work.
_CELLS = """
WITH cells AS (
  SELECT u.c >> %(regroup)s AS c, sum(u.n)::bigint AS n
    FROM ({parts}) u
   GROUP BY 1
)
SELECT ST_AsMVT(f, 'points', %(extent)s, 'geom') FROM (
  SELECT ST_Point((app.morton_compact(c.c) - %(cx0)s + 0.5) * %(unit)s,
                  (app.morton_compact(c.c >> 1) - %(cy0)s + 0.5) * %(unit)s) AS geom,
         c.n
    FROM cells c
   WHERE c.c >> %(inside)s = %(tile)s OR c.c = ANY(%(margin)s::bigint[])
) f
"""


def _margin_cells(z: int, x: int, y: int, cell_zoom: int) -> tuple[int, list[int]]:
    """How many cells a side the margin has (centres within BUFFER of the tile edge), and the
    keys of those cells around tile z/x/y at `cell_zoom` (inside the world, no wrap-around)."""
    k = 2 ** (cell_zoom - z)
    unit = EXTENT // k
    depth = int(BUFFER / unit + 0.5)
    n = 2**cell_zoom
    cells = []
    for i in range(-depth, k + depth):
        for j in range(-depth, k + depth):
            if 0 <= i < k and 0 <= j < k:
                continue
            cx, cy = x * k + i, y * k + j
            if 0 <= cx < n and 0 <= cy < n:
                cells.append(morton(cx, cy))
    return depth, cells


@dataclass(frozen=True)
class TimeParts:
    """[start, end) split for the roll-up: whole UTC years (`years`, a [lo, hi) range of
    1 January dates, None = unbounded), whole UTC days (`days`), and the partial days at the ends,
    read from raw points (`raw`). None as a whole means no year part."""

    years: tuple[dt.date | None, dt.date | None] | None
    days: list[tuple[dt.date, dt.date]]
    raw: list[tuple[dt.datetime | None, dt.datetime | None]]


def _midnight(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC)


def split_range(start: dt.datetime | None, end: dt.datetime | None) -> TimeParts:
    if not USE_ROLLUP:
        return TimeParts(None, [], [(start, end)])
    d_lo = d_hi = None
    if start is not None:
        utc = start.astimezone(dt.UTC)
        d_lo = utc.date() + dt.timedelta(days=0 if utc == _midnight(utc.date()) else 1)
    if end is not None:
        d_hi = end.astimezone(dt.UTC).date()
    if d_lo is not None and d_hi is not None and d_lo >= d_hi:
        return TimeParts(None, [], [(start, end)])
    raw: list[tuple[dt.datetime | None, dt.datetime | None]] = []
    if start is not None and d_lo is not None and start < _midnight(d_lo):
        raw.append((start, _midnight(d_lo)))
    if end is not None and d_hi is not None and _midnight(d_hi) < end:
        raw.append((_midnight(d_hi), end))
    y_lo = None if d_lo is None else dt.date(d_lo.year + (d_lo.timetuple().tm_yday > 1), 1, 1)
    y_hi = None if d_hi is None else dt.date(d_hi.year, 1, 1)
    if y_lo is not None and y_hi is not None and y_lo >= y_hi:
        assert d_lo is not None and d_hi is not None
        return TimeParts(None, [(d_lo, d_hi)], raw)
    days = []
    if d_lo is not None and y_lo is not None and d_lo < y_lo:
        days.append((d_lo, y_lo))
    if d_hi is not None and y_hi is not None and y_hi < d_hi:
        days.append((y_hi, d_hi))
    return TimeParts((y_lo, y_hi), days, raw)


# Pieces of `_count_parts`: fixed SQL with integer constants and bound-parameter conditions.
_ROLLUP_PART = (
    "SELECT r.cell AS c, r.n FROM history_pointrollup r"
    " WHERE r.level = {level} AND r.grain = {grain} AND {cells}{more}"
)
_RAW_PART = (
    "SELECT p.tile_key >> {shift} AS c, count(*) AS n FROM history_locationpoint p"
    " WHERE {keys}{more} GROUP BY 1"
)


def _count_parts(
    level: int,
    ranges: list[tuple[int, int]],
    start: dt.datetime | None,
    end: dt.datetime | None,
    sources: Sequence[str] | None,
    params: dict,
) -> str:
    """A UNION ALL of (c, n) rows - c a cell at `level`, n its count - for the caller's points
    inside the key ranges and [start, end): roll-up rows for whole years and days, raw points
    for the rest. RLS on both tables limits it to the caller's own history."""
    parts = split_range(start, end)
    source = ""
    if sources:
        params["sources"] = list(sources)
        source = " AND {alias}.source = ANY(%(sources)s)"

    def bound(column: str, op: str, value) -> str:
        if value is None:
            return ""
        name = f"t{len(params)}"
        params[name] = value
        return f" AND {column} {op} %({name})s"

    selects = []
    shift = 2 * (KEY_ZOOM - level)
    periods = [(GRAIN_DAY, lo, hi) for lo, hi in parts.days]
    if parts.years is not None:
        periods.insert(0, (GRAIN_YEAR, *parts.years))
    for grain, lo, hi in periods:
        cells = _key_condition(ranges, params, "r.cell", shift)
        conditions = bound("r.period", ">=", lo) + bound("r.period", "<", hi)
        selects.append(
            _ROLLUP_PART.format(
                level=int(level), grain=int(grain), cells=cells, more=conditions + source
            ).replace("{alias}", "r")
        )
    for lo, hi in parts.raw:
        keys = _key_condition(ranges, params)
        conditions = bound("p.ts", ">=", lo) + bound("p.ts", "<", hi)
        selects.append(
            _RAW_PART.format(shift=int(shift), keys=keys, more=conditions + source).replace(
                "{alias}", "p"
            )
        )
    return "\n   UNION ALL ".join(selects)


# Segments by key (index on owner_id, seg_key for current versions), then the exact envelope.
_SEGMENT_JOIN = "JOIN history_timelinesegment s ON {keys} AND s.geom && q.outer4326"

_COUNT_SEGMENTS = (
    _ENVELOPE  # noqa: S608
    + """
SELECT count(*) FROM (
  SELECT 1 FROM q {segments}
   WHERE s.is_current {filters}
   LIMIT %(cap)s
) c
"""
)

_SEGMENTS = (
    _ENVELOPE  # noqa: S608
    + """
SELECT ST_AsMVT(f, 'segments', %(extent)s, 'geom') FROM (
  SELECT ST_AsMVTGeom(ST_Simplify(ST_Transform(s.geom, 3857), q.px), q.tile, %(extent)s,
                      %(buffer)s, true) AS geom,
         s.id,
         s.kind,
         s.activity_type AS activity,
         s.semantic_type AS semantic,
         extract(epoch FROM s.start_utc)::bigint AS t0,
         extract(epoch FROM s.end_utc)::bigint AS t1
    FROM q {segments}
   WHERE s.is_current {filters}
) f
WHERE f.geom IS NOT NULL
"""
)

# Too many segments for one tile: every geometry is snapped to a SEGMENT_LATTICE x
# SEGMENT_LATTICE lattice over the tile, and segments that end up identical (same shape, kind
# and activity) become one feature with their number `n` and time span. Nothing is dropped
# unless even the merged features exceed MAX_SEGMENT_FEATURES (then the most travelled stay).
_MERGED_SEGMENTS = (
    _ENVELOPE  # noqa: S608
    + """
, snapped AS (
  SELECT ST_AsMVTGeom(
           ST_SnapToGrid(ST_Transform(s.geom, 3857), q.x0, q.y0, q.snap, q.snap),
           q.tile, %(extent)s, %(buffer)s, true) AS geom,
         s.kind, s.activity_type, s.start_utc, s.end_utc
    FROM (SELECT q.*, q.px * %(extent)s / %(lattice)s AS snap FROM q) q {segments}
   WHERE s.is_current {filters}
), merged AS (
  SELECT geom, kind, activity_type AS activity, count(*) AS n,
         extract(epoch FROM min(start_utc))::bigint AS t0,
         extract(epoch FROM max(end_utc))::bigint AS t1
    FROM snapped
   WHERE geom IS NOT NULL
   GROUP BY geom, kind, activity_type
)
SELECT (SELECT ST_AsMVT(f, 'segments', %(extent)s, 'geom') FROM (
          SELECT * FROM merged ORDER BY n DESC, t1 DESC LIMIT %(features)s) f),
       (SELECT count(*) FROM merged)
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
    params = _base_params(z, x, y)
    if z >= POINTS_MIN_ZOOM:
        count_params: dict = {}
        parts = _count_parts(KEY_ZOOM, [key_range(z, x, y)], start, end, sources, count_params)
        (count,) = _run(f"SELECT coalesce(sum(u.n), 0) FROM ({parts}) u", count_params)  # noqa: S608
        if count <= MAX_POINTS_PER_TILE:
            filters, filter_params = _filters("p", start, end, sources)
            params |= filter_params
            sql = _POINTS.format(points=_point_join(key_ranges(z, x, y), params), filters=filters)
            (data,) = _run(sql, params)
            return Tile(bytes(data or b""), aggregated=False)
    # Cells GRID_BITS zoom levels down, but no finer than the keys: a dense tile at zoom 14+
    # gets 2^(20 - z) cells a side (64 at z14, 16 at z16) instead of GRID.
    cell_zoom = min(z + GRID_BITS, KEY_ZOOM)
    level = next(level for level in ROLLUP_LEVELS if level >= cell_zoom)
    k = 2 ** (cell_zoom - z)
    params = {
        "extent": EXTENT,
        "regroup": 2 * (level - cell_zoom),
        "cx0": x * k,
        "cy0": y * k,
        "unit": EXTENT // k,
        "inside": 2 * (cell_zoom - z),
        "tile": morton(x, y),
        "margin": _margin_cells(z, x, y, cell_zoom)[1],
    }
    parts = _count_parts(level, key_ranges(z, x, y), start, end, sources, params)
    (data,) = _run(_CELLS.format(parts=parts), params)
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
    overlapping [start, end): one feature each, or merged (`aggregated`, with `n`) when there are
    more than MAX_SEGMENTS_PER_TILE."""
    check_tile(z, x, y, min_zoom=SEGMENTS_MIN_ZOOM)
    filters, params = "", _base_params(z, x, y)
    if start is not None:
        filters += " AND s.end_utc >= %(start)s"
        params["start"] = start
    if end is not None:
        filters += " AND s.start_utc < %(end)s"
        params["end"] = end
    ranges, ancestors = segment_keys(z, x, y)
    keys = _key_condition(ranges, params, "s.seg_key")
    if ancestors:
        params["ancestors"] = ancestors
        keys = f"({keys} OR s.seg_key = ANY(%(ancestors)s::bigint[]))"
    sql = {"filters": filters, "segments": _SEGMENT_JOIN.format(keys=keys)}
    params["cap"] = MAX_SEGMENTS_PER_TILE + 1
    (count,) = _run(_COUNT_SEGMENTS.format(**sql), params)
    if count <= MAX_SEGMENTS_PER_TILE:
        (data,) = _run(_SEGMENTS.format(**sql), params)
        return Tile(bytes(data or b""), aggregated=False)
    params |= {"lattice": SEGMENT_LATTICE, "features": MAX_SEGMENT_FEATURES}
    data, merged = _run(_MERGED_SEGMENTS.format(**sql), params)
    return Tile(bytes(data or b""), aggregated=True, truncated=merged > MAX_SEGMENT_FEATURES)


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
