# NEXT-43c

Handoff for work-order item 43c (lane 3, branch item/43c): don't lose a save to the hourly
re-check (D-108, D-120). Fold into NEXT.md at merge, then delete this file.

- **Done (2026-11-24), D-122 (amends D-108 (1) and D-120):** `travel.accounts.sessions.recheck`
  returns ALLOW / REFUSE / END per request. Once the stamp is older than the interval, reads
  (GET, HEAD, OPTIONS, any other method) are signed out with the 401 `DUE_DETAIL` as before
  (pages redirect), but the session is kept; writes (POST, PUT, PATCH, DELETE) pass for a grace
  of the interval, at most an hour (`MAX_GRACE_SECONDS`). Past the grace, or without a stamp,
  any request ends the session. `RlsContextMiddleware` maps REFUSE to an anonymous request
  without `logout`. Bearer tokens unchanged. No migration, no API change, no frontend change
  (a comment in `auth/recheck.ts` only).
- **Bound after removal from travel-users:** reads within the interval (1 h), writes within
  interval + grace (2 h), `deactivate_account` at once. Restated in go-live.md "Removing
  someone's access", auth.md §7.2/§7.7, permissions.md, production.md, the deactivate command's
  docstring.
- **Tests:** `backend/tests/test_session_recheck.py` (per method: fresh, due within the grace,
  end of the grace, past it, never stamped; the cap; other methods count as reads; sign-out);
  `tests/test_authentik.py` (round trips through the fake provider: a save across the check
  survives re-sign-in, past the grace nothing is written, a refused callback ends the session
  so no grace, Authentik refusing on its side ends writes at two hours, bearer tokens have no
  grace). `./dev e2e --recheck` now saves a preference (`e2e_recheck`) within the grace and
  checks it after the silent sign-in; the go-live smoke's F-3 checks a save and a read at
  90 minutes and a save at 3 hours.
- **Verified in the lane:** targeted tests green; `./dev e2e --recheck` green (the lane .env
  line was added and removed again); `./dev golive-smoke local` PASS (101 checks);
  `./dev test-quick` 2744 + 192 passed; lint clean. Lane stack down.
- **Open:** a read during the edit after the check fell due (React Query's refetch when the tab
  regains focus, a place search while typing) still redirects and loses the input. Closing it
  needs forms to hold the redirect while they have unsaved input (fe:auth registry plus the
  forms in fe:trips); the server already keeps the session for their save. Candidate follow-up
  item. If lane 2 also took D-122, renumber one at merge. The delta review after 40c-3 should
  include 43c (an auth change).
