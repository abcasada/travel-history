# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight:** none. Item 2 (T4 + T2) built by builder-xhigh on 2026-11-10/11, awaiting the orchestrator's check. T4: D-76 (row policy on `accounts_user` + `accounts_userdirectory` view; matrix now 49 actions × 7 = 343 cases). T2: D-77 (`travel/core/ratelimit.py` on the `ratelimit` DB alias; not wired to tracker paths, item 7 does that). `./dev test` 513 + 18 passed, lint and type checks green. For Adam: D-76's directory also shows person link + active flag (beyond names-only D-72); confirm or ask for names only.
- **Next:** the orchestrator verifies item 2, then item 3 (T5) in docs/ROADMAP.md. Apply docs/pending-adam-input.md after item 2 as planned. Q-11's radius stays open. The HDD alert below may affect anything that writes to `/bulk`.
- **Host alert (2026-11-11 00:19 UTC):** `/storage/hdd1` (`/dev/sda1`, ext4) is mounted `emergency_ro` and returns I/O errors, so `/bulk` (raw files, uploads, backup outbox) is unwritable; the e2e upload step gets a 500. Host/disk problem for Adam; not touched.
- **Waiting on Adam:** AGE_RECIPIENT, his Timeline export and flight spreadsheet in data/private/, and an optional ORS key. Item 4 stays deferred until the key and the export are there.
- **Notes:** PLAN.md is now an index; design is in docs/design/, decisions in docs/decisions.md. Use `./dev test-quick` at item ends and `./dev test` at milestones. Base images are pinned by version and digest; bump them deliberately and re-run the CPU smoke check.
