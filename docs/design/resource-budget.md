# Resource budget

Moved from PLAN.md §21 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 21. Resource budget

Target host: Ryzen 5 3600 (6C/12T), 32 GB RAM, SSD + HDD. Measured numbers replace these
after the first real import.

| Component | CPU | RAM | Disk | Notes |
|---|---|---|---|---|
| Travel app: `web` | 1 core steady | 768 MB cap | — | gunicorn 2 workers × 4 threads |
| Travel app: `ingest` (tracker endpoint before go-live, D-85; production stack since D-96) | idle except tracker posts | 512 MB cap (~190 MB measured 2026-11-17) | — | same image as `web`, 2 workers × 4 threads; retired or kept tracker-only at go-live |
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

**After work-order item 5a (2026-11-17, same test and data, D-86).** Point tiles and the
coverage strip read the trigger-maintained roll-up (`history_pointrollup`, history migrations
0010 and 0013); segments are found by `seg_key` (0011) and dense segment tiles are merged instead
of truncated. ms over HTTP through runserver (~55–65 ms of that is runserver), first then warm:

| Tile | z0 | z3 | z6 | z10 | z13 | z16 | z18 |
|---|---|---|---|---|---|---|---|
| points, all history: before | 2145 / 923 / 926 | 1564 / 1479 / 1547 | 1786 / 1769 / 1785 | 1352 / 1296 / 1322 | — | 4839 / 1668 / 2001 | — |
| points, all history: after | 199 / 50 / 50 | 894 / 62 / 63 | 783 / 94 / 83 | 757 / 128 / 129 | 755 / 274 / 265 | **76** / 73 / 84 | 57 / 56 / 61 |
| points, one year: before | 416 / 359 / 347 | 400 / 425 / 403 | 460 / 442 / 428 | 379 / 400 / 416 | — | 616 / 633 / 1120 | — |
| points, one year: after | 415 / 57 / 55 | 134 / 94 / 71 | 67 / 84 / 79 | 83 / 91 / 93 | 132 / 132 / 171 | 76 / 80 / 61 | 56 / 77 / 56 |
| segments, all history: before | — | — | 683 / 161 / 170 (cut at 3,000) | 176 / 167 / 173 (cut) | — | 162 / 153 / 151 (cut) | — |
| segments, all history: after | — | — | 1058 / 318 / 342 (merged, 1 KiB) | 426 / 421 / 408 (merged, 93 KiB) | 577 / 518 / 471 (merged; cut at 10,000 features) | 329 / 344 / 330 (merged, 216 KiB) | — |
| segments, one year: after | — | — | 146 / 149 / 129 (merged) | 146 / 163 / 167 (merged) | 195 / 186 / 185 | 169 / 151 / 164 | — |

- Targets: whole-history point tiles under 300 ms warm at every zoom (worst z13, 265–274 ms,
  273 KiB: about 18,000 cells of 37 m over the dense home area) — **met**; z16 under 1 s cold
  (76 ms) — **met**. The first request at each zoom after the import is 0.2–0.9 s while the
  roll-up's pages are read from disk.
- Coverage strip, one year: before 1,037 ms; after 411 ms on that first, cold request over HTTP
  (the run timed it once) and 85 ms warm in-process (~145 ms over HTTP), from the hourly
  roll-up rows. The script now times it three times.
- Segment tiles no longer drop segments: dense tiles merge coinciding (simplified, 4-px-snapped)
  lines with a count `n`. They take 0.3–0.5 s over the dense home area for the whole history
  (they used to stop at the newest 3,000). Only the whole-history z13 tile still exceeds 10,000
  merged features in this synthetic data (each path vertex is jittered ±22 m, so tracks rarely
  coincide at 76 m spacing); it keeps the most travelled.
- Cost: the import took 1,330 s instead of 972 s (+37 %, the triggers' upserts; worker memory
  unchanged, peak RSS 271 MiB). The roll-up holds 2.33 M rows (1.79 M day, 0.47 M year, 68 k
  hour) in 429 MB (heap 191, indexes 238), 36 % on top of the points' 1,197 MB: about 465 B per
  point all-in, so 20 M points ≈ 9.3 GB, still inside the 60 GB SSD budget. If space gets tight,
  the cheapest cut is the surrogate `id` column and its index (a composite primary key), or
  coarser time buckets than days at zoom 18–20. Cleanup through the delete trigger left no rows.

### 21.2 Measured: Valhalla Kansas build and service (2026-11-18, work-order item 17)

`./dev valhalla build` with the Geofabrik Kansas extract (113 MiB, Last-Modified 2026-11-17),
image `valhalla-scripted:3.9.1` (pinned by digest), 2 build threads, elevation and transit off,
admins and time zones on, on the Xeon W3565 with the data on the SSD (`valhalla/data/`).
Numbers from the build's `BUILD_INFO.json`, cgroup `memory.peak` and `docker stats`.

| Measure | Result | routing.md §13.5 estimate |
|---|---|---|
| Build time | **188 s**: download 43, time zones 14 (fetches the shapefile), admins 5, tiles 124, tar 1 | tens of minutes |
| Build peak RAM | **773 MiB** anonymous; 1,977 MiB cgroup peak including page cache (4 GiB limit) | < 2 GB |
| Disk | build directory 422 MB (tiles.tar + admins + time zones); loose tiles (298 MB) deleted after tarring; extract 113 MB; `valhalla/data/` 534 MB total. During a rebuild the new build sits beside the old one (≈ +0.7 GB peak) | ~1–2 GB |
| Service RAM | 130 MiB idle after the smoke test; **237 MiB peak** after a 15,880-point map-match (1 GiB limit) | a few hundred MB |
| Latency | route Wichita → Salina (144.7 km): 410 ms first request; map-match of 2,891 points: 312 ms; 15,880 points: 0.8 s | — |

All well inside the estimates. The NA figures in §13.5 remain unmeasured estimates.

### 21.3 Measured: GeoNames gazetteer (2026-11-18, work-order item 14)

`./dev manage load_gazetteer`, pinned snapshot of 2026-11-18, on the Xeon W3565 with the dev
stack running.

| What | Measured |
|---|---|
| Downloads cached in `/bulk/reference` | 85 MB: `cities500.zip` 13.9 MB, `US.zip` 71.1 MB (307 MB unzipped, read straight from the zip), `countryInfo.txt` 32 kB, `admin1CodesASCII.txt` 152 kB |
| Rows | 385,097 places: 237,315 from cities500 + 147,782 more from the 168,827 US populated places kept (PPL, PPLA–PPLA5, PPLC, PPLL, PPLS, PPLF, STLMT; neighbourhoods and abandoned or historical places skipped); 252 countries, 3,865 admin-1 names |
| DB | `geo_geonamesplace` 202 MB (heap 117 MB, indexes 85 MB incl. two prefix indexes ≈ 19 MB each); names tables 1 MB. Dev DB 301 MB → 504 MB |
| Load time | about 3 min 15 s for all four files (re-runs upsert, same time) |
| Search | 2–55 ms on the dev DB (a 2-letter prefix like "sa" is the slow end) |

Worth it: the US small-town file costs ~70 MB of download and ~80 MB of DB for every small Kansas
town GeoNames knows. Well inside the SSD budget.

### 21.4 Measured: production and development stacks side by side (2026-11-19, work-order item 40a)

The production stack (`travel-history-prod`, D-96) runs beside the development stack on the
Xeon W3565 (11 GiB RAM, 4 GiB swap), with Authentik and the Kansas Valhalla running too and the
other apps as usual. Production was freshly deployed and empty (item 40b copies the data in);
development held Adam's real data (batch 33, 385,097 gazetteer places). `free -m` and
`docker stats` (anonymous memory; page cache excluded), sampled idle:

| What | Before production | With production |
|---|---|---|
| Host `available` | 5,777 MiB | **5,210 MiB** |
| Host `used` / swap used | 5,650 MiB / 521 MiB | 6,217 MiB / 521 MiB |
| All containers | — | 3,995 MiB |

| Container | Measured | Cap (`mem_limit`) |
|---|---|---|
| prod `db` (empty) | 75 MiB | 1,536 MiB (`shared_buffers` 512 MB, as dev) |
| prod `web` (gunicorn 2 × 4, read-only root) | 198 MiB | 768 MiB |
| prod `worker` | 91 MiB | 1,536 MiB |
| prod `backup` | 1 MiB | 512 MiB |
| prod `ingest` (stopped; ~190 MiB when running, §21) | — | 512 MiB |
| prod `tools` (one-off `./dev prod manage`) | — | 1,536 MiB |
| dev `db` (real data) | 589 MiB | 1,536 MiB |
| dev `web` (runserver) / `worker` | 168 / 107 MiB | 768 / 1,536 MiB |
| dev `frontend` (Vite) / `oidc` / `mail` | 478 / 130 / 11 MiB | 1,280 / 512 / 128 MiB |
| Authentik server / worker / PostgreSQL | 666 / 282 / 148 MiB | none |
| Valhalla (Kansas) | 236 MiB | 1,024 MiB |

- **Production costs about 370 MiB idle while empty.** With the real data (item 40b: about
  0.6 GB of tables, mostly points and the gazetteer) its database should settle near the dev
  database's 0.6 GiB, so expect about 0.9–1.2 GiB for production in steady use. That leaves
  roughly 4.5 GiB available with everything running.
- **The caps follow §21's per-service budget** (production ≤ 4.3 GiB if every service hit its
  cap at once, which an import and a backup at the same moment could approach). They are
  ceilings, not reservations; the host can't satisfy both stacks at their caps together, so
  heavy development work (scale tests, imports in dev) shouldn't overlap production imports.
- **Easy headroom when it gets tight:** once Adam enters data only in production (item 40c),
  the dev `frontend`, `oidc` and `mail` (about 620 MiB) can stay stopped between builder
  sessions. The Ryzen host (32 GB) removes the constraint.
