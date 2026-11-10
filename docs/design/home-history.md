# Home history

Moved from PLAN.md §10 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 10. Home history

### 10.1 Suggestion algorithm ("dominant sleeping location")

1. For each local night *n* (local time from the point's time zone, via `timezonefinder` on the
   first point of the night), collect the owner's points and visit segments between 01:00 and
   05:00 local.
2. Cluster that night's points with `ST_ClusterDBSCAN(eps = 150 m, minpoints = 3)` (visits
   contribute their centroid weighted by duration). The night's location is the cluster with the
   most dwell time, if it covers ≥ 50 % of the window; otherwise the night is "unknown".
3. Snap night locations to stable sites: cluster all night locations of the person (eps 150 m) →
   site ids.
4. Walk nights in order with a 28-night sliding window. A site is the *candidate home* when it is
   the location on ≥ 60 % of known nights in the window.
5. A **move** is suggested when the candidate home changes and the new site holds for ≥ 21 days
   (configurable). The suggested boundary is between the last night at the old site and the
   first night at the new one; precision is `day` if they are adjacent nights, else
   `approximate` with the gap recorded in `evidence`.
6. Hints: Google `HOME`/`INFERRED_HOME` labels (visit `semanticType` and
   `userLocationProfile` frequent places, if present — §8.1) boost a site's score and are shown
   as evidence; they never override the night data.
7. Runs of ≥ 21 nights at a non-home site while a home exists elsewhere are suggested as
   **long stay** (e.g. a work assignment), not as a move.

The user confirms, edits or rejects each suggestion and sets `kind` (home or long stay).
Rejected suggestions are remembered by (site, date range) and not re-suggested.

### 10.2 Manual entry and validation

- Address (geocoded against GeoNames/boundaries for a rough point; the user drags the pin to the
  exact spot) or map point, with from/to dates and precisions — covers childhood homes too.
- Validation flags **gaps** (no home period covering a span between the first and last known
  homes) and **overlaps** (allowed only when both periods have `overlap_allowed`).
