# Resource budget

Moved from PLAN.md §21 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 21. Resource budget

Target host: Ryzen 5 3600 (6C/12T), 32 GB RAM, SSD + HDD. Measured numbers replace these
after the first real import.

| Component | CPU | RAM | Disk | Notes |
|---|---|---|---|---|
| Travel app: `web` | 1 core steady | 768 MB cap | — | gunicorn 2 workers × 4 threads |
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
