# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **Item 25 (T23 + T24) built, 2026-11-19:** routing proxy `POST /api/v1/routing/route` (Valhalla in Kansas → ORS when `ORS_API_KEY` is set → FOSSGIS 1 req/s), per-user proposal cache under RLS, `POST /legs/{id}/routes` saves the caller's cached proposal as a frozen version (attribution column, simplified copies), leg route page proposes/saves with via points, e2e routes a Kansas leg. D-92 recorded (not locked; no approval needed unless Adam objects). Final check: `./dev test-quick` at item end.
- **Order next:** 26 (drag editor, [H]) → 21a → 21b (scopes in docs/design/frontend-patterns.md §8) → review pause B → 11, 12, 14… Item 4 (real Timeline import, about 150 MB) jumps the queue when AGE_RECIPIENT and data/private/Timeline.json are both present; its wipe must keep tracker data. Tracking (item 8) is on hold and the ingest service is stopped.
- **Done and verified:** items 1, 2, 3, 5, 5a, 6, 7, 9, 10, 13, 17, 20 (25 built, see above) (details in ROADMAP changelog). Valhalla (Kansas) runs as the separate `valhalla` compose project.
- **Waiting on Adam:** approve D-89 (contribution rules), D-90 (catalog UI choices), D-91 (Valhalla setup), recommended yes for all three; ORS_API_KEY in .env (the ORS path is built and mock-tested; then restart web/worker); the age1 public key for AGE_RECIPIENT; Timeline.json and the flight spreadsheet in data/private/; a replacement HDD (then move var/bulk back, D-84, and run `./dev restore-test`).
- **Fix items to queue later:** the smoke test's expectations for Cloudflare's robots.txt and 404s; Colota's 400s (_type missing) when tracking resumes; at go-live, one canonical host (travel vs trips); the security review (item 41) should check whether the dev app on 8780 was reachable via travel.adamcasada.com before 2026-11-17.
- **Host:** the HDD /dev/sda is failing and unmounted; /bulk is on the SSD at var/bulk (D-84). About 60 GB SSD free.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` (about 4.5 min) at item ends, `./dev test` at milestones.
