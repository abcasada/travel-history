# Resource budget

Moved from PLAN.md §21 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 21. Resource budget

Target host: Ryzen 5 3600 (6C/12T), 32 GB RAM, SSD + HDD. Measured numbers replace these
after the first real import.

| Component | CPU | RAM | Disk | Notes |
|---|---|---|---|---|
| Travel app: `web` | 1 core steady | 768 MB cap | — | gunicorn 2 workers × 4 threads |
| Travel app: `ingest` (tracker endpoint before go-live, D-85) | idle except tracker posts | 512 MB cap (~190 MB measured 2026-11-17) | — | same image as `web`, 2 workers × 4 threads; retired or kept tracker-only at go-live |
| Travel app: `worker` | 1 core steady, bursts to 3–4 during imports | 1.5 GB cap | — | streaming imports keep memory flat |
| Travel app: `db` (PostGIS) | shared | 1.5 GB cap (`shared_buffers` 512 MB) | ~60 GB SSD at maturity | points table dominates (~100 B/row + indexes; 20 M points ≈ 5 GB) |
| Travel app total | 2 steady, 4 burst | **≤ 4 GB** | 60 GB SSD | |
| Raw import archive | — | — | ~50 GB HDD | zstd ≈ 10–15 % of JSON size |
| Basic photos | — | — | ~10 GB HDD to start | 2048 px display + 400 px thumbs |
| Backup outbox | — | — | ≈ size of DB dump + raw + photos (encrypted) on HDD | |
| Valhalla NA (shared) | 1–2 cores | ~2 GB steady (page cache) | ~100 GB SSD budget; 20–35 GB steady after build, 120–150 GB during a build | build peak RAM ≈ 16–28 GB (§13.5) |
| Authentik (separate project) | 1 core | ~2–2.5 GB (server 0.5–0.8 GB, worker 0.5–1 GB, PostgreSQL; no Redis since 2025.10) | ~2 GB | |
| Immich | separate project, not counted | | | ML container needs x86-64-v2 |

**Current host (Xeon W3565, 11 GiB, 28 GB free SSD):** fine for development with synthetic data,
a Kansas Valhalla extract and a few years of real history (≈ 3–4 GB RAM for the stack). It
cannot hold the North America build, and the 60 GB SSD budget does not fit until the migration
(or until the ~55 GB unallocated in the volume group is added to the root LV — a host change, Q-3).

### 21.1 Measured: 1 GB synthetic Timeline import (2026-11-17, work-order item 3, audit #4)

Repeatable with `./dev import-scale-test [size_mb]` (scripts/import-scale-test.sh +
backend/tests/scale/import_scale.py; not part of any pytest suite). It streams a synthetic Android
on-device export (jittered public city centres, ~10 years, a road trip a month; raw positions every
60 s from 06:00 to 22:00, wifiScan + activityRecord every 5 min), uploads it over HTTP through the
chunked upload API as a throwaway user, lets the dev worker archive and import it, measures, and
deletes everything again. It fails if the import fails, counts differ, or the worker's peak RSS
reaches its limit. Host: Xeon W3565, dev stack (runserver, worker under watchfiles), bulk on the
SSD (D-84).

| Measure | Result |
|---|---|
| File | 1,081 MB JSON: 37,571 segments (17,067 visits, 10,193 activities, 10,193 paths, 118 memories), 209,962 path points, 3,412,800 raw positions, 1,365,120 other signals; 3,555 days |
| Generate | 100 s |
| Upload (33 × 32 MB chunks over HTTP) | 37 s |
| Archive (SHA-256, zstd, verify) | 35 s; raw file 96 MB (8.8 % of the JSON) |
| Import (parse, diff, insert) | 972 s (16.2 min), ≈ 3,700 points/s |
| Worker peak RSS (VmHWM) | **272 MiB of the 1,536 MiB limit (18 %)**; sampled anon peak 230 MiB; cgroup memory.peak 818 MiB including reclaimable page cache. A 20 MB run peaked at 209 MiB, so memory stays flat with size. |
| Counts | all match: 3,412,800 google_raw + 209,962 google_path points; segments by kind identical |
| DB growth | 1,241 MB total. `history_locationpoint` +1,198 MB (heap 540, indexes 659) for 3.62 M points ≈ 347 B/point all-in; `history_timelinesegment` +43 MB (heap 30, indexes 11) |
| Cleanup | rows deleted, VACUUM FULL; DB back to 22 MB, var/bulk back to 24 KB |

Budget check: **pass**. Memory is far under the cap; no time budget is set, and 16 min per GB is
acceptable for a one-off import. The DB row above underestimates points: at ~350 B/point,
20 M points ≈ 7 GB (not 5 GB), still inside the 60 GB SSD budget.

History tiles against this volume (one user, 3.62 M points, ANALYZEd; tile over the dense home
area; ms for 3 requests, first then warm; runserver adds ~65 ms, measured on empty tiles):

| Tile | z0 | z3 | z6 | z10 | z16 |
|---|---|---|---|---|---|
| points, all history | 2145 / 923 / 926 | 1564 / 1479 / 1547 | 1786 / 1769 / 1785 | 1352 / 1296 / 1322 | 4839 / 1668 / 2001 (aggregated: > 10,000 points) |
| points, one year (`from`/`to`) | 416 / 359 / 347 | 400 / 425 / 403 | 460 / 442 / 428 | 379 / 400 / 416 | 616 / 633 / 1120 |
| segments, all history | — | — | 683 / 161 / 170 (truncated at 3,000) | 176 / 167 / 173 (truncated) | 162 / 153 / 151 (truncated) |
| segments, one year | — | — | 141 / 138 / 140 (truncated) | 149 / 145 / 141 (truncated) | 134 / 128 / 136 |

Coverage strip for one year: 1,037 ms (365 days). All tiles stayed under the 10 s statement
timeout, but whole-history point tiles take 1–2 s each (≈ 5 s cold at z16), so a map view of
~12 tiles is slow. This is the input for item 5a's per-day grid roll-up. Segment tiles are fine
at this volume but are always truncated over the home area.
