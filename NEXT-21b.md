# NEXT-21b (lane handoff)

- **Item 21b done (2026-11-24), on branch item/21b; merge waits for 40e (backend freeze).**
  Trip page complete (tags, notes, per-leg people, "I was on this leg", public consent,
  participants' own legs and their notes, flight airline/seat/cabin and airport codes), `/tags`,
  `/purposes`, `/people` (account menu), trip status filter. API: `TripStatus` enum (also on
  `TripOut.status`), `PATCH /persons/{id}`, `POST/PATCH /purposes`, `GET /reference/airlines`,
  `airline`/`origin_airport`/`destination_airport` on `LegOut`, `PersonOut.manages`; D-113.
- **Migration:** new `backend/travel/accounts/migrations/0005_person_update_needs_member.py`
  (RLS `person_update` now needs `app.can_create()` unless Admin). No `geo` migration, so 14a-1's
  geo migrations don't conflict. In `geo`, only `geo/api.py` changed (airline search).
- **Tests:** `tests/permissions/test_trip_page_api.py`, 5 new matrix rows (113 × 7); Vitest
  `TripPage.test.tsx`, `ListsPages.test.tsx`, plus additions to the edit, list and filter tests;
  e2e extended (the flight leg is added after the drag editor on purpose, because a wider map
  changes its anchors). In the lane: `./dev test-quick` backend 2811 passed; frontend 204/205.
  The failure is 21a's `TitleSearch.test.tsx` "fast typing" test, which is flaky (timing; fails
  about 1 run in 3; this item doesn't touch it; worth a small fix item). e2e green.
- **At merge:** rebase on main. ShellMenu.tsx got three links (43b works near its sign-in
  handling). Regenerate the client if main's schema moved (`export_openapi` + `gen:api`).
- **Left:** the leg vehicle picker waits for item 23 (TODO in `toLegPayload`).
