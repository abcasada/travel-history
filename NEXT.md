# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight (2026-11-18):** item 14b (stop and leg notes), builder-medium. If interrupted, re-dispatch with the interruption rule. Then 40a (G-1 to G-5 answered; G-6: keep the Timeline raw file).
- **Order after that:** 40a → 40b → 40c → 40d → 41a → (42a) → pause (findings + exposure "go") → 40e → 14c (spreadsheet importer) → 4 → 21 → 27 → pause B → 11 → 12 → pause A → 15 … 24 → 14a → 28, then 29–46.
- **Adam's go-live answers (defaults):** public at travel.adamcasada.com behind Authentik 2FA (exposure needs his explicit "go" and his tunnel change); trips.* redirects to travel.*; he creates family accounts in Authentik (group `travel-users`), they become Members; request-access form later; focused security review before go-live; dev-admin's data moves to his real account. Authentik runs on the host; he's setting it up per docs/design/auth.md §7.2.
- **Dev DB holds real data:** Adam's Timeline import (batch 33: 193,009 points, 53,438 segments) and hand-entered trips. Never wipe it. Don't restart web/worker during an import.
- **Done and verified:** items 1, 2, 3, 5, 5a, 6, 7, 9, 10, 13, 14, 17, 20, 25, 26. ORS live. GeoNames loaded in dev (385,097 places). Spreadsheet design merged (docs/design/trip-sheet.md §28, template docs/trips/trip-template.xlsx, D-95).
- **Notes for later items:** 40a/40b must copy the cached GeoNames files or re-pin with `load_gazetteer --latest`. Spreadsheet importer: add defusedxml; Notes columns for stops and legs if the notes item lands; item 11 links sheet flight legs to flight records. GeoNames alternate names aren't loaded ("München" finds nothing).
- **Waiting on Adam (other):** the age1 public key for AGE_RECIPIENT (real data has no encrypted backup yet); the flight spreadsheet in data/private/; a replacement HDD (then move var/bulk back, D-84, and run `./dev restore-test`).
- **Fix items to queue:** pre-commit gitleaks scans 0 commits inside git worktrees (make the hook mount the common git dir); the smoke test's expectations for Cloudflare's robots.txt and 404s; Colota's 400s when tracking resumes; the review should check whether the dev app on 8780 was reachable via travel.adamcasada.com before 2026-11-17; item 27 editor polish; a pre-existing basemap glyph 404 in e2e.
- **Host:** the HDD /dev/sda is failing and unmounted; /bulk is on the SSD at var/bulk (D-84).
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` (about 4.5 min) at item ends, `./dev test` at milestones.
