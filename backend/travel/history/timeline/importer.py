"""Google Timeline importer with re-import diffing (PLAN.md §8.2-8.3).

Rules that must hold (CLAUDE.md rules 6-7):
  * segments are matched by time overlap (same kind and nesting level), never exact timestamps;
  * an identical segment is skipped; a changed one becomes a new version and the old version is
    kept; a segment absent from a newer export is never deleted;
  * in-app edits win: Google's differing version is stored but not made current;
  * confirmed trips whose source segments changed get a review flag and are not modified.
The work runs in the worker in short per-chunk transactions as the batch owner, so a crash
leaves a consistent partial import that a re-run completes (identical segments are skipped).
"""

from __future__ import annotations

import bisect
import datetime as dt
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from itertools import islice

from django.contrib.gis.geos import LineString, Point
from django.db import connection
from django.db.models import Max
from django.utils import timezone

from travel.core.rls import rls_context
from travel.history import importers, rawstore
from travel.history.models import ImportBatch, PlaceHint, PointSource, TimelineSegment
from travel.trips.models import Leg, ReviewFlag, Stop, Trip

from .formats import IOS, ParseStats, PathPoint, Segment, detect, iter_hints, iter_raw_points
from .formats import iter_segments as parse_segments

SEGMENT_CHUNK = 2000
POINT_BATCH = 5000
PAD = dt.timedelta(seconds=60)
MIN_DURATION = 60.0  # seconds; zero-length segments count as one minute for overlap ratios
IDENTICAL_OVERLAP = 0.9
CHANGED_OVERLAP = 0.5
MERGED_OVERLAP = 0.8  # share of an extra old segment covered by the new one (Google merged)
HOME_TYPES = {"HOME", "INFERRED_HOME"}
WORK_TYPES = {"WORK", "INFERRED_WORK"}


def _chunks(items: Iterable, size: int) -> Iterator[list]:
    iterator = iter(items)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _duration(start: dt.datetime, end: dt.datetime) -> float:
    return max((end - start).total_seconds(), MIN_DURATION)


def _overlap_ratio(a_start, a_end, b_start, b_end) -> float:
    """Shared time relative to the shorter segment (0..1). Instants (zero-length segments) count
    as fully overlapping when they fall inside or within a minute of the other segment."""
    shared = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
    if shared < -PAD.total_seconds():
        return 0.0
    shared = max(shared, 0.0)
    if a_start == a_end or b_start == b_end:
        shared = max(shared, MIN_DURATION)
    return min(shared / min(_duration(a_start, a_end), _duration(b_start, b_end)), 1.0)


def _geometry(segment: Segment):
    coords = [(lon, lat) for lat, lon in segment.coords]
    if not coords:
        return None
    if len(coords) == 1 or len(set(coords)) == 1:
        return Point(*coords[0], srid=4326)
    return LineString(coords, srid=4326)


def _nudge_ties(points: list[PathPoint]) -> list[PathPoint]:
    """iOS path times have minute precision; spread points sharing a timestamp by one second
    each so none is lost to the (owner, source, ts) de-duplication."""
    seen: Counter = Counter()
    out = []
    for point in points:
        offset = seen[point.ts]
        seen[point.ts] += 1
        out.append(
            PathPoint(point.ts + dt.timedelta(seconds=offset), point.lat, point.lon)
            if offset
            else point
        )
    return out


class _Candidates:
    """Current segments of one (kind, level) in a chunk's time span, sorted by start."""

    def __init__(self, rows: list[TimelineSegment]):
        self.rows = sorted(rows, key=lambda r: r.start_utc)
        self.starts = [r.start_utc for r in self.rows]
        self.longest = max((r.end_utc - r.start_utc for r in self.rows), default=dt.timedelta())
        self.consumed: set[int] = set()

    def overlapping(self, start: dt.datetime, end: dt.datetime) -> list[TimelineSegment]:
        hi = bisect.bisect_right(self.starts, end + PAD)
        out = []
        for row in reversed(self.rows[:hi]):
            if row.start_utc < start - PAD - self.longest:
                break
            if row.pk in self.consumed or row.end_utc < start - PAD:
                continue
            out.append(row)
        return out


class _Diff:
    def __init__(self, owner_id: int, batch_id: int):
        self.owner_id = owner_id
        self.batch_id = batch_id
        self.counts: Counter = Counter()
        self.by_kind: dict[str, Counter] = defaultdict(Counter)
        self.identical_existing: set[int] = set()
        self.superseded: list[tuple[int, int]] = []  # (old id, new id)
        self.span_start: dt.datetime | None = None
        self.span_end: dt.datetime | None = None

    def _row(self, segment: Segment, lineage, version: int, current: bool) -> TimelineSegment:
        data = segment.canonical()
        data["probability"] = segment.probability
        return TimelineSegment(
            owner_id=self.owner_id,
            lineage_id=lineage,
            version=version,
            is_current=current,
            kind=segment.kind,
            start_utc=segment.start,
            end_utc=segment.end,
            utc_offset_min=segment.utc_offset_min,
            hierarchy_level=segment.hierarchy_level,
            place_id=segment.place_id[:255],
            semantic_type=segment.semantic_type[:32],
            activity_type=segment.activity_type[:32],
            probability=segment.probability,
            geom=_geometry(segment),
            distance_m=segment.distance_m,
            data=data,
            fingerprint=segment.fingerprint,
            import_batch_id=self.batch_id,
        )

    def apply(self, segments: list[Segment]) -> None:
        """Diff one chunk and write it (inside the caller's transaction)."""
        lo = min(s.start for s in segments) - PAD
        hi = max(s.end for s in segments) + PAD
        self.span_start = lo + PAD if self.span_start is None else min(self.span_start, lo + PAD)
        self.span_end = hi - PAD if self.span_end is None else max(self.span_end, hi - PAD)
        rows = (
            TimelineSegment.objects.filter(
                owner_id=self.owner_id, is_current=True, start_utc__lte=hi, end_utc__gte=lo
            )
            .exclude(import_batch_id=self.batch_id)
            .only(
                "id",
                "lineage_id",
                "kind",
                "hierarchy_level",
                "start_utc",
                "end_utc",
                "fingerprint",
                "edited_in_app",
            )
        )
        buckets: dict[tuple[str, int], list] = defaultdict(list)
        for row in rows:
            buckets[(row.kind, row.hierarchy_level)].append(row)
        candidates = {key: _Candidates(value) for key, value in buckets.items()}

        new_rows: list[TimelineSegment] = []
        replacements: list[tuple[list[int], int]] = []  # (old ids, index into new_rows)
        lineage_versions: dict = {}
        pending_versions: list[tuple[int, Segment, object, bool]] = []

        for segment in segments:
            bucket = candidates.get((segment.kind, segment.hierarchy_level))
            matches = bucket.overlapping(segment.start, segment.end) if bucket else []
            fingerprint = segment.fingerprint
            if any(m.fingerprint == fingerprint for m in matches):
                same = next(m for m in matches if m.fingerprint == fingerprint)
                self.identical_existing.add(same.pk)
                self._count("identical", segment)
                continue
            scored = sorted(
                (
                    (_overlap_ratio(segment.start, segment.end, m.start_utc, m.end_utc), m)
                    for m in matches
                ),
                key=lambda pair: pair[0],
                reverse=True,
            )
            if scored and scored[0][0] >= CHANGED_OVERLAP:
                best = scored[0][1]
                if best.edited_in_app:
                    # In-app edits win: keep Google's version, but not as the current one.
                    pending_versions.append((len(new_rows), segment, best.lineage_id, False))
                    new_rows.append(None)  # placeholder, filled after version lookup
                    self._count("kept_app_edit", segment)
                    continue
                olds = [best.pk]
                for _ratio, other in scored[1:]:
                    covered = _overlap_ratio_of(other, segment)
                    if covered >= MERGED_OVERLAP and not other.edited_in_app:
                        olds.append(other.pk)
                for pk in olds:
                    bucket.consumed.add(pk)
                pending_versions.append((len(new_rows), segment, best.lineage_id, True))
                new_rows.append(None)
                replacements.append((olds, len(new_rows) - 1))
                self._count("changed", segment)
                self.counts["merged_superseded"] += len(olds) - 1
                continue
            new_rows.append(self._row(segment, uuid.uuid4(), 1, True))
            self._count("new", segment)

        if pending_versions:
            lineages = {lineage for _, _, lineage, _ in pending_versions}
            for item in (
                TimelineSegment.objects.filter(lineage_id__in=lineages)
                .values("lineage_id")
                .annotate(top=Max("version"))
            ):
                lineage_versions[item["lineage_id"]] = item["top"]
            for index, segment, lineage, current in pending_versions:
                lineage_versions[lineage] = lineage_versions.get(lineage, 0) + 1
                new_rows[index] = self._row(segment, lineage, lineage_versions[lineage], current)

        superseded_ids = [pk for olds, _ in replacements for pk in olds]
        if superseded_ids:
            # Free the "one current version per lineage" slot before inserting the new version.
            TimelineSegment.objects.filter(pk__in=superseded_ids).update(is_current=False)
        created = TimelineSegment.objects.bulk_create(new_rows, batch_size=500)
        pairs = [(old, created[index].pk) for olds, index in replacements for old in olds]
        if pairs:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE history_timelinesegment t SET superseded_by_id = v.new "
                    "FROM unnest(%s::bigint[], %s::bigint[]) AS v(old, new) WHERE t.id = v.old",
                    [[p[0] for p in pairs], [p[1] for p in pairs]],
                )
            self.superseded.extend(pairs)

    def _count(self, outcome: str, segment: Segment) -> None:
        self.counts[outcome] += 1
        self.by_kind[segment.kind][outcome] += 1


def _overlap_ratio_of(row: TimelineSegment, segment: Segment) -> float:
    """Share of `row`'s own duration covered by `segment`."""
    shared = (min(row.end_utc, segment.end) - max(row.start_utc, segment.start)).total_seconds()
    return max(shared, 0.0) / _duration(row.start_utc, row.end_utc)


class _PointWriter:
    SQL = """
        INSERT INTO history_locationpoint
            (owner_id, ts, geom, accuracy_m, altitude_m, speed_mps, source, import_batch_id,
             received_at)
        SELECT %s, u.ts, ST_SetSRID(ST_MakePoint(u.lon, u.lat), 4326), u.acc, u.alt, u.spd,
               %s, %s, now()
        FROM unnest(%s::timestamptz[], %s::float8[], %s::float8[], %s::float8[], %s::float8[],
                    %s::float8[]) AS u(ts, lat, lon, acc, alt, spd)
        ON CONFLICT ON CONSTRAINT point_dedupe DO NOTHING
    """

    def __init__(self, owner_id: int, batch_id: int):
        self.owner_id = owner_id
        self.batch_id = batch_id
        self.seen: Counter = Counter()
        self.inserted: Counter = Counter()
        self.buffer: dict[str, list[tuple]] = defaultdict(list)

    def add(self, source: str, ts, lat, lon, acc=None, alt=None, spd=None) -> None:
        self.seen[source] += 1
        rows = self.buffer[source]
        rows.append((ts, lat, lon, acc, alt, spd))
        if len(rows) >= POINT_BATCH:
            self.flush(source)

    def flush(self, source: str | None = None) -> None:
        for name in [source] if source else list(self.buffer):
            rows = self.buffer.pop(name, [])
            if not rows:
                continue
            columns = list(zip(*rows, strict=True))
            with rls_context(self.owner_id), connection.cursor() as cursor:
                cursor.execute(self.SQL, [self.owner_id, name, self.batch_id, *map(list, columns)])
                self.inserted[name] += cursor.rowcount


def _flag_confirmed_trips(owner_id: int, superseded: list[tuple[int, int]], batch_id: int) -> int:
    """Confirmed trips built on segments that just got new versions are flagged, not changed."""
    if not superseded:
        return 0
    new_for_old = dict(superseded)
    old_ids = list(new_for_old)
    trips: dict[int, set[int]] = defaultdict(set)
    for leg in Leg.objects.filter(
        trip__owner_id=owner_id,
        trip__status=Trip.Status.CONFIRMED,
        source_segments__overlap=old_ids,
    ).only("trip_id", "source_segments"):
        trips[leg.trip_id].update(s for s in leg.source_segments if s in new_for_old)
    for stop in Stop.objects.filter(
        trip__owner_id=owner_id,
        trip__status=Trip.Status.CONFIRMED,
        source_segment_id__in=old_ids,
    ).only("trip_id", "source_segment_id"):
        trips[stop.trip_id].add(stop.source_segment_id)
    for trip_id, olds in trips.items():
        ReviewFlag.objects.create(
            trip_id=trip_id,
            reason=ReviewFlag.Reason.SOURCE_CHANGED,
            details={
                "import_batch": batch_id,
                "segments": [{"old": old, "new": new_for_old[old]} for old in sorted(olds)],
            },
        )
    Trip.objects.filter(pk__in=list(trips)).update(needs_review=True)
    return len(trips)


@importers.register(ImportBatch.Kind.GOOGLE_TIMELINE)
def import_timeline(batch: ImportBatch) -> dict:
    owner_id, batch_id = batch.owner_id, batch.pk
    raw = batch.raw_file

    def open_stream():
        return rawstore.open_original(raw)

    variant = detect(open_stream)
    stats = ParseStats()
    diff = _Diff(owner_id, batch_id)
    points = _PointWriter(owner_id, batch_id)
    hints: set[tuple] = set()
    total_segments = 0

    for chunk in _chunks(parse_segments(open_stream, variant, stats), SEGMENT_CHUNK):
        total_segments += len(chunk)
        with rls_context(owner_id):
            diff.apply(chunk)
        for segment in chunk:
            if segment.kind == "path":
                for point in _nudge_ties(segment.points) if variant == IOS else segment.points:
                    points.add(PointSource.GOOGLE_PATH, point.ts, point.lat, point.lon)
            elif segment.kind == "visit" and segment.coords:
                label = (
                    "HOME"
                    if segment.semantic_type in HOME_TYPES
                    else "WORK"
                    if segment.semantic_type in WORK_TYPES
                    else None
                )
                if label:
                    lat, lon = segment.coords[0]
                    hints.add((label, segment.place_id, lat, lon))
    for point in iter_raw_points(open_stream, variant, stats):
        points.add(
            PointSource.GOOGLE_RAW,
            point.ts,
            point.lat,
            point.lon,
            point.accuracy_m,
            point.altitude_m,
            point.speed_mps,
        )
    points.flush()
    for hint in iter_hints(open_stream, variant, stats):
        hints.add((hint.label, hint.place_id, hint.lat, hint.lon))

    with rls_context(owner_id):
        new_hints = 0
        for label, place_id, lat, lon in hints:
            _, created = PlaceHint.objects.get_or_create(
                owner_id=owner_id,
                label=label,
                place_id=place_id[:255],
                defaults={"point": Point(lon, lat, srid=4326), "import_batch_id": batch_id},
            )
            new_hints += created
        flagged = _flag_confirmed_trips(owner_id, diff.superseded, batch_id)
        absent = 0
        if diff.span_start is not None:
            in_span = (
                TimelineSegment.objects.filter(
                    owner_id=owner_id,
                    is_current=True,
                    start_utc__lte=diff.span_end,
                    end_utc__gte=diff.span_start,
                )
                .exclude(import_batch_id=batch_id)
                .count()
            )
            absent = max(in_span - len(diff.identical_existing), 0)

    return {
        "format": variant,
        "format_verified": variant != IOS,  # PLAN.md D-38
        "segments": {
            "total": total_segments,
            "identical": diff.counts["identical"],
            "new": diff.counts["new"],
            "changed": diff.counts["changed"],
            "merged_superseded": diff.counts["merged_superseded"],
            "kept_app_edits": diff.counts["kept_app_edit"],
            "absent_kept": absent,
            "by_kind": {kind: dict(counter) for kind, counter in diff.by_kind.items()},
        },
        "points": {
            source: {
                "seen": points.seen[source],
                "inserted": points.inserted[source],
                "duplicates": points.seen[source] - points.inserted[source],
            }
            for source in points.seen
        },
        "place_hints_new": new_hints,
        "trips_flagged_for_review": flagged,
        "time_span": {
            "start": diff.span_start.isoformat() if diff.span_start else None,
            "end": diff.span_end.isoformat() if diff.span_end else None,
        },
        "warnings": stats.warnings,
        "warning_count": stats.warning_count,
        "imported_at": timezone.now().isoformat(),
    }
