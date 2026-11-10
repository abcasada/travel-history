# Google Timeline import

Moved from PLAN.md §8 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 8. Google Timeline import

Scope: only the current on-device Timeline export (Android and iOS). Older Takeout formats
(`Records.json`, Semantic Location History) are out of scope. Imports are per user.

### 8.1 Format (no official schema; see `docs/research/formats-trackers-datasets.md`)

| | Android export | iOS export (**unverified until checked against a real iOS sample**) |
|---|---|---|
| Root | object: `semanticSegments[]`, `rawSignals[]`, `userLocationProfile{}` | bare array of segments |
| Segment | `startTime`, `endTime` (ISO 8601 with offset), `startTimeTimezoneUtcOffsetMinutes`, one of `visit` / `activity` / `timelinePath` / `timelineMemory` | `startTime`, `endTime` (mixed `Z` and offsets), one of `visit` / `activity` / `timelinePath` |
| Coordinates | `"lat°, lng°"` strings, wrapped as `{"latLng": …}` (`LatLng` in rawSignals) | `"geo:lat,lng"` strings, unwrapped |
| Numbers | JSON numbers | strings (`"0.598864"`) |
| Place id key | `placeId` | `placeID` |
| Semantic types | `HOME`, `WORK`, `INFERRED_HOME`, `INFERRED_WORK`, `SEARCHED_ADDRESS`, `ALIASED_LOCATION`, `UNKNOWN` | `Home`, `Work`, `Searched Address`, `Aliased Location`, `Unknown` |
| Activity types | `IN_PASSENGER_VEHICLE`, `FLYING`, `WALKING`, `IN_TRAIN`, `IN_BUS`, `IN_FERRY`, … | `in passenger vehicle`, `flying`, `walking`, `in train`, … |
| Path points | `{point, time}` (absolute time) | `{point, durationMinutesOffsetFromStartTime}` (minute precision); path records grouped at the end |
| Raw signals | `position` (`LatLng`, `accuracyMeters`, `altitudeMeters`, `source`, `timestamp`, `speedMetersPerSecond`), `wifiScan`, `activityRecord` | none |
| Home/work hints | visit `semanticType` + `userLocationProfile.frequentPlaces[].label` | visit `semanticType` only |
| Place names | **none** — only Google place IDs (verified across sources) | none |

The parser detects the variant by root type and keys, normalizes both to one internal
representation (UTC times, float lat/lon, upper-case enums, absolute path times), and keeps the
original bytes untouched in the raw store. `wifiScan` and `activityRecord` are not imported
(kept only in the raw file). Place names come from local reverse geocoding (§15).

Mapping: `visit` → `timeline_segment(kind=visit)` (+ `place` with `google_place_id`);
`activity` → `kind=activity` with mode; `timelinePath` → `kind=path` and its points into
`location_point(source=google_path)`; `rawSignals.position` → `location_point(source=google_raw)`;
`timelineMemory` → `kind=memory` (trip hints for detection).

### 8.2 Pipeline

1. **Upload** (web or companion) through the resumable chunked upload API (§17). Chunks are
   written to a temp file while a SHA-256 is computed incrementally.
2. **Raw file:** if `(owner, sha256)` exists → "identical file already imported", link to its
   batch, stop. Otherwise stream through zstd into `/bulk/raw/<owner>/<sha256>.json.zst`,
   `chmod 0440`, decompress-verify the hash, insert `raw_file` (immutable) and `import_batch`.
3. **Parse** in the worker with `ijson` (C backend), one segment at a time; memory stays bounded
   regardless of file size. Each segment is normalized (canonical key order, rounded coordinates
   to 1e-7°, ISO times → UTC) and fingerprinted (SHA-256 of the canonical JSON).
4. **Stage:** normalized segments are bulk-inserted in chunks of 2,000 into an `UNLOGGED`
   staging table keyed by batch. Points from `timelinePath` and `rawSignals.position` are
   inserted straight into `location_point` (`ON CONFLICT DO NOTHING`).
5. **Diff** in SQL against the owner's current segments (below).
6. **Downstream:** confirmed trips whose source segments got new versions get a `review_flag`;
   detection is re-run for affected date ranges only (locked trips untouched); coverage reports
   are recomputed for affected days; home suggestions refreshed.
7. **Summary** stored in `import_batch.summary` and shown: identical, new, changed (new versions),
   kept-but-absent, points added, duplicate points skipped, flagged trips, parse warnings.

### 8.3 Re-import diff algorithm

For each staged segment `s` (same owner, same `kind`), find current segments `c` whose
`time_range` overlaps `s.time_range` (GiST index):

```
overlap(s, c) = |s ∩ c| / min(|s|, |c|)          # 0..1, zero-length ranges use ±60 s
if any c with c.fingerprint == s.fingerprint and overlap ≥ 0.9  → IDENTICAL (skip)
elif best c by overlap has overlap ≥ 0.5:
     if c.edited_in_app                                    → KEEP c (in-app edits win);
                                                             store s as a non-current version
                                                             and note "import differs" in summary
     else                                                  → CHANGED: insert s as new version of
                                                             c.lineage (version+1, is_current),
                                                             mark c not current, superseded_by = s
                                                             also supersede any other current c'
                                                             overlapped ≥ 0.8 by s (Google merged
                                                             segments)
else                                                       → NEW: new lineage, version 1
Current segments with no staged counterpart                → untouched (ABSENT ≠ DELETED)
```

- Matching is by time overlap within the same `kind` **and nesting level** (`hierarchy_level`:
  Google nests visits, e.g. a shop inside a mall), never exact timestamps (Google shifts
  boundaries by seconds). Segments created by the same import are never superseded by it.
- The fingerprint covers the segment's content (times to the second, place id, semantic and
  activity type, coordinates to 1e-6°, distance, path points) but **not** Google's probability,
  which changes without any user edit.
- Implementation: the diff runs in Python per chunk of 2,000 segments against the owner's current
  segments in that chunk's time span (GiST range index), with set-based writes; each chunk is
  its own transaction, so an interrupted import is completed by a re-run (`rerun_import`).
- A split (one old visit → two new) is handled because each new piece overlaps the old one
  ≥ 0.5 of the shorter: the first becomes the new version, the second a new lineage that
  supersedes nothing else.
- Old versions are never deleted. `timeline_segment` rows are append-only except the
  `is_current`/`superseded_by` pointer.
- In-app edits always win; confirmed trips are never silently changed — they get a
  `review_flag(reason=source_changed)` listing old vs new segment versions.
