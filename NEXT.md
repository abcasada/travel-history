# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **Item 7 (T7) built 2026-11-16, awaiting orchestrator verification.** Tracker endpoints `/api/v1/ingest/{owntracks,overland}`, token API `/api/v1/tracking/tokens`, Trackers page (`/app/trackers`), docs/tracking/, D-82, Q-17 (GPSLogger hosted link skipped). Full suite green (1,248 backend + 31 frontend), lint clean, e2e ok (only the known /api/v1/uploads 500 from /bulk).
- **For item 8:** set `TRACKER_BASE_URL` (public origin), `RATELIMIT_CLIENT_IP_HEADER=CF-Connecting-IP` only if every request comes through the tunnel, `DJANGO_BEHIND_TLS_PROXY=true`, HSTS, allowed hosts, DEBUG off; rebuild the production image (its gunicorn access log now omits query strings); route only the two ingest paths. Cloudflare terminates TLS, so it sees tokens and payloads. Items 1, 2, 5 and 6 are done and verified.
- **Next:** item 8 (tracker exposure) needs Adam's "go" and DNS record, so ask him as soon as item 7 lands, then continue with item 9. Item 3 is blocked (HDD), item 4 is deferred, item 5a waits on item 3.
- **For item 13:** the scope and the notes/tracks alignment are listed in ROADMAP.md item 13; details are in docs/design/permissions.md.
- **Item 5 note:** the Morton `tile_key` and InitPlan RLS policies are documented in docs/design/map-rendering.md §14; Adam was asked whether to record them as a decision. The follow-ups are now item 5a in ROADMAP.md.
- **Host alert (2026-11-11):** `/storage/hdd1` (`/dev/sda1`, Hitachi HDD) is mounted `emergency_ro` with I/O errors, so `/bulk` is unwritable and the e2e upload step returns a 500. Adam is told; nothing on the disk was touched. A failed write probe may have left an empty `.probe` in /storage/hdd1/travel-history/raw.
- **Waiting on Adam:** fix the disk; confirm Q-10 (Resend) and Q-12 (keep gitleaks); confirm the D-76 directory's extra fields (person link, active flag); confirm D-81 and answer Q-16; AGE_RECIPIENT; Timeline export and flight spreadsheet in data/private/; optional ORS key.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` at item ends, `./dev test` at milestones.
