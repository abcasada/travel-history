# NEXT-43c

Handoff for work-order item 43c (lane 3, branch item/43c): don't lose a save to the hourly
re-check (D-108, D-120).

- **Plan:** `travel.accounts.sessions` decides per request: fresh → pass; due within the grace
  (the interval, at most an hour) → reads refused as signed out (session kept), writes
  (POST/PUT/PATCH/DELETE) pass; past the grace or no stamp → the session ends, 401. Decision
  D-122. Tests in tests/test_authentik.py; e2e/recheck.mjs gains a save within the grace;
  golive-smoke F-3 checks a write in the grace and a write past it; docs (auth.md §7.2/§7.7,
  go-live.md, development.md, PLAN index).
- **Status:** in progress.
