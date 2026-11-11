# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight:** item 6 (T18 core), builder-xhigh: code, tests, OpenAPI client and docs committed (f575a66); running the full suite, then push. Items 1, 2 and 5 are done and verified.
- **Next:** item 7 (T7) after item 6. Item 3 is blocked by the failing HDD, item 4 is deferred, and item 5a waits on item 3.
- **Item 5 note:** the Morton `tile_key` and InitPlan RLS policies are documented in docs/design/map-rendering.md §14; Adam was asked whether to record them as a decision. The follow-ups are now item 5a in ROADMAP.md.
- **Host alert (2026-11-11):** `/storage/hdd1` (`/dev/sda1`, Hitachi HDD) is mounted `emergency_ro` with I/O errors, so `/bulk` is unwritable and the e2e upload step returns a 500. Adam is told; nothing on the disk was touched. A failed write probe may have left an empty `.probe` in /storage/hdd1/travel-history/raw.
- **Waiting on Adam:** fix the disk; confirm Q-10 (Resend) and Q-12 (keep gitleaks); confirm the D-76 directory's extra fields (person link, active flag); AGE_RECIPIENT; Timeline export and flight spreadsheet in data/private/; optional ORS key.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` at item ends, `./dev test` at milestones.
