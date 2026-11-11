# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight:** item 2 (T4 + T2), builder-xhigh. Plan: T4 = tighten `accounts_user` SELECT to self/Admin/auth context + a `security_barrier` directory view (id, display_name, person_id, is_active) for family, new migration accounts 0003, D-76; T2 = `travel/core/ratelimit.py` on a dedicated autocommit DB alias, D-77. Sub-steps are committed as they land. T4 done (D-76, matrix 49 actions × 7 = 343 cases).
- **Next:** work order item 2 (T4 + T2) in docs/ROADMAP.md; T4 follows D-72 (names only), which Adam re-confirmed on 2026-11-10. Start-of-run questions were answered on 2026-11-10 (PLAN.md §25); Q-11's radius stays open.
- **Host alert (2026-11-11 00:19 UTC):** `/storage/hdd1` (`/dev/sda1`, ext4) is mounted `emergency_ro` and returns I/O errors, so `/bulk` (raw files, uploads, backup outbox) is unwritable; the e2e upload step gets a 500. Host/disk problem for Adam; not touched.
- **Waiting on Adam:** AGE_RECIPIENT, his Timeline export and flight spreadsheet in data/private/, and an optional ORS key. Item 4 stays deferred until the key and the export are there.
- **Notes:** PLAN.md is now an index; design is in docs/design/, decisions in docs/decisions.md. Use `./dev test-quick` at item ends and `./dev test` at milestones. Base images are pinned by version and digest; bump them deliberately and re-run the CPU smoke check.
