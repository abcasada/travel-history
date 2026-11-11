# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight:** none. Item 5 (T6, milestone 2.3) built 2026-11-11 and pushed; awaits orchestrator verification. Full suite 603 + 26 green, lint/types green, e2e green except the known /bulk upload 500.
- **Next:** verify item 5, then item 6 (T18 core). Item 3 blocked by the failing HDD; item 4 deferred.
- **Item 5 follow-ups:** proposed decision for decisions.md (needs Adam): Morton `tile_key` + `(SELECT app.is_family())` InitPlan policies, because PostGIS `&&` isn't LEAKPROOF under RLS (details in docs/design/map-rendering.md §14). Deferred: per-day grid roll-up for low-zoom tiles on multi-million-point histories; segment tiles have no spatial key yet; `./dev restore-test` not run (reads /bulk) — run it after the disk fix to confirm the generated `tile_key` column restores.
- **Host alert (2026-11-11):** `/storage/hdd1` (`/dev/sda1`, Hitachi HDD) is mounted `emergency_ro` with I/O errors, so `/bulk` is unwritable and the e2e upload step returns a 500. Adam is told; nothing on the disk was touched. A failed write probe may have left an empty `.probe` in /storage/hdd1/travel-history/raw.
- **Waiting on Adam:** fix the disk; confirm Q-10 (Resend) and Q-12 (keep gitleaks); confirm the D-76 directory's extra fields (person link, active flag); AGE_RECIPIENT; Timeline export and flight spreadsheet in data/private/; optional ORS key.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` at item ends, `./dev test` at milestones.
