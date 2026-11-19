# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight (2026-11-18):** planner-xhigh re-plans per Adam's requests in the ROADMAP changelog (2026-11-18 entries): item 14 (city search) next, then a minimal family go-live slice. If interrupted, re-dispatch the planner.
- **Adam's go-live answers (defaults):** public at travel.adamcasada.com behind Authentik 2FA (exposure still needs his explicit "go" and his tunnel change); trips.* redirects to travel.*; he creates family accounts in Authentik (group `travel-users`), they become Members; request-access form stays later; a focused security review before go-live; dev-admin's data (import, trips, tracker points) moves to his real account at first sign-in. Authentik already runs on the host (authentik-* containers); he's setting up the app/provider per docs/design/auth.md §7.2.
- **Dev DB holds real data:** Adam imported his Timeline through the app (batch 33, 193,009 points). Never wipe it; item 4's "wipe synthetic data" must be re-planned. Don't restart web/worker during an import.
- **Done and verified:** items 1, 2, 3, 5, 5a, 6, 7, 9, 10, 13, 17, 20, 25, 26. ORS is live (ORS_API_KEY set; Denver→Boulder test route via ORS). Valhalla (Kansas) runs as the separate `valhalla` compose project.
- **Waiting on Adam:** approve D-89, D-90, D-91, D-92 (routing proxy), D-93 (saving edited routes), recommended yes for all five; the age1 public key for AGE_RECIPIENT (real data has no encrypted backup yet); the flight spreadsheet in data/private/; a replacement HDD (then move var/bulk back, D-84, and run `./dev restore-test`).
- **Fix items to queue later:** the smoke test's expectations for Cloudflare's robots.txt and 404s; Colota's 400s (_type missing) when tracking resumes; the security review should check whether the dev app on 8780 was reachable via travel.adamcasada.com before 2026-11-17. Item 27 (editor polish): anchor popup, touch, `sources` in the version list, re-proposing expired spans.
- **Host:** the HDD /dev/sda is failing and unmounted; /bulk is on the SSD at var/bulk (D-84).
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` (about 4.5 min) at item ends, `./dev test` at milestones.
