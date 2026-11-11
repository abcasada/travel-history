# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight:** item 5 (T6), dispatched to builder-high 2026-11-11. Items 1 and 2 done and verified 2026-11-11; Adam's 2026-11-10 answers applied (D-78..D-80, PLAN.md §25, MIT LICENSE).
- **Next:** item 5 (T6 raw-history map). Item 3 is blocked by the failing HDD; item 4 is deferred.
- **Host alert (2026-11-11):** `/storage/hdd1` (`/dev/sda1`, Hitachi HDD) is mounted `emergency_ro` with I/O errors, so `/bulk` is unwritable and the e2e upload step returns a 500. Adam is told; nothing on the disk was touched. A failed write probe may have left an empty `.probe` in /storage/hdd1/travel-history/raw.
- **Waiting on Adam:** fix the disk; confirm Q-10 (Resend) and Q-12 (keep gitleaks); confirm the D-76 directory's extra fields (person link, active flag); AGE_RECIPIENT; Timeline export and flight spreadsheet in data/private/; optional ORS key.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` at item ends, `./dev test` at milestones.
