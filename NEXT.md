# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **Item 6 (T18 core) built**, awaiting orchestrator verification: travel/trips/api.py + services.py, trips migration 0003, matrix 344 → 456 cases, tests/permissions/test_trips_api.py (351) and test_trip_guards.py (8). Items 1, 2 and 5 are done and verified.
- **Next:** item 7 (T7) after item 6. Item 3 is blocked by the failing HDD, item 4 is deferred, and item 5a waits on item 3.
- **For item 13 (rest of T18):** tags, stops, notes/media/tracks, routes listing, bulk, duplicates/join/merge, leg reorder, the remaining list filters (purpose, tag, vehicle, mode, bbox). Notes and tracks still let an ex-participant author edit/delete while the trip is visible (RLS + `policy.can_edit_contribution`), looser than §6.3 "Member — other ❌"; legs were tightened in item 6, align these the same way. Q-16 (owner deleting a removed participant's leg) and D-81 await Adam.
- **Item 5 note:** the Morton `tile_key` and InitPlan RLS policies are documented in docs/design/map-rendering.md §14; Adam was asked whether to record them as a decision. The follow-ups are now item 5a in ROADMAP.md.
- **Host alert (2026-11-11):** `/storage/hdd1` (`/dev/sda1`, Hitachi HDD) is mounted `emergency_ro` with I/O errors, so `/bulk` is unwritable and the e2e upload step returns a 500. Adam is told; nothing on the disk was touched. A failed write probe may have left an empty `.probe` in /storage/hdd1/travel-history/raw.
- **Waiting on Adam:** fix the disk; confirm Q-10 (Resend) and Q-12 (keep gitleaks); confirm the D-76 directory's extra fields (person link, active flag); confirm D-81 and answer Q-16; AGE_RECIPIENT; Timeline export and flight spreadsheet in data/private/; optional ORS key.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` at item ends, `./dev test` at milestones.
