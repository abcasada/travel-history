# NEXT-21b (lane handoff)

- **In flight:** item 21b (trip page complete + TripStatus enum fix). Branch item/21b.
- **Done:** backend (commit "21b backend"): `TripStatus` enum, `PATCH /persons/{id}`,
  `POST/PATCH /purposes`, `GET /reference/airlines`, `airline`/`origin_airport`/`destination_airport`
  refs on `LegOut`, new migration `accounts/0005_person_update_needs_member.py` (D-113), tests in
  `tests/permissions/test_trip_page_api.py`, matrix rows; client regenerated.
- **Next:** frontend (status filter, trip page sections, tags/people/purposes pages, leg form for
  contributors, flight fields), Vitest, e2e step, docs (D-113, permissions §6.3 notes, patterns §8).
