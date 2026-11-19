# Roadmap

Only the orchestrator and the planner edit this file. Status values: todo · in progress · done · deferred · blocked.

## Work order

> **Execution order (2026-11-18, planner, from Adam's 2026-11-18 priorities: city search, then family go-live):**
> **14** → **40a** → **40b** → **40c** (build and final copy, then the handover after Adam's first sign-in) → **40d** → **41a** → **42a** (only if 41a finds blockers) → **pause: 41a's findings + the exposure "go"** → **40e** → **4** → 21 (21a list tools, 21b trip page; frontend-patterns.md §8) → 27 → **Review pause B** → 11 → 12 → **Review pause A** → 15 → 16 → 18 → 19 → 22 → 23 → 24 → 14a → 28, then 29–46 in number order (40 and 41 are now the rest of T38 and the full final review).
> Location tracking (item 8's last step) stays on hold; when it resumes, it deploys the production stack's `ingest` (40a), never dev's. Earlier orders are in the changelog.
>
> **Go-live gates:** 40a waits for G-1; 40c's handover for G-3 and G-4; 40e for G-2's backup, 41a's blockers fixed, and Adam's "go" plus his tunnel change; item 4 for G-6. Adam pastes the Authentik client secret and `AGE_RECIPIENT` into `.env.prod` himself. From 40c's final copy on, Adam enters data only in production. Family members sign in only after 40e. If answers are missing when an item needs them, run 21 and 27 meanwhile.
>
> **Questions for Adam (2026-11-18). All PROPOSED: not approved until Adam answers. Recommended defaults in bold.**
> - **G-1 Separate production stack (40a):** its own compose project, DB volume and `.env.prod`, web on `127.0.0.1:8784` (dev keeps :8780 and :5173), bulk storage outside the repo on the SSD, deployed only from pushed `main`. This amends D-28's port and needs a CLAUDE.md environment-note update. **Yes.**
> - **G-2 Backups before go-live (40b, 40e):** go-live requires `AGE_RECIPIENT` and one encrypted production backup whose restore test passes. It sits on the same SSD until the NAS pull exists. **Yes, and send the age1 public key now:** the trips typed into dev exist only there, with no backup.
> - **G-3 Handover method (40c):** the first Authentik sign-in creates an empty account. An owner-only command then moves that Authentik login onto the old dev-admin account, so every row stays put, and deletes the empty account. Accounts are never matched by email. **Yes.**
> - **G-4 Sign-in test before exposure (40c):** over an SSH port-forward to localhost (Q-8's method), which needs a temporary second redirect URI `http://localhost:8784/auth/callback` in the Authentik provider, removed at go-live. **Yes.** If no, the first real sign-in and the handover happen right after exposure.
> - **G-5 Second-factor check (40c):** refuse sign-ins whose Authentik ID token shows no second factor (`amr`), if Authentik reports one. This is defence in depth if the flow is ever misconfigured. **Yes.**
> - **G-6 Dev cleanup (item 4, deleting real data):** delete the dev copy of the real data (dev DB volume and `var/bulk` raw archive) once production's copy is verified and backed up. Export files in `data/private/` are untouched. **Yes.**
> - Still open from earlier: D-89 to D-93 (**yes** to all).

Tiers: [M] builder-medium, [H] builder-high, [X] builder-xhigh, [R] reviewer-xhigh. Task IDs (T1…T46) and finding numbers (#1…#16) are from the 2026-10-21 audit; their descriptions and dependencies are in the Task reference below. Each item is one dispatch unless noted.

1. **[M] Stage 0 housekeeping** (details below). Skip it if already done.
   - Status: done (2026-11-10)

   **Item 1 details: Stage 0 housekeeping**
   1. **Restructure PLAN.md** (it's ~35k tokens):
      - It becomes an index of 400 lines or fewer: status, a pointer to ROADMAP.md, open questions, one line per decision, and links to the docs.
      - Move §3–§22 to `docs/design/<area>.md`, and §1 plus the facts register (§26) to `docs/research/`.
      - Merge the decisions log into `docs/decisions.md`, keeping the entries already there.
      - Verify that every old heading appears in exactly one new file, and that the word count, excluding the new index, is within 2% of the original. Report both checks.
   2. **Enrich docs/ROADMAP.md** with each task's description and dependencies from STATUS.md, without changing the order or tiers. Then delete STATUS.md without committing it.
   3. **Add deny rules in `.claude/settings.json`** for reading `frontend/src/api/generated.ts`, `frontend/dist/`, minified bundles, and lockfiles. Verify the rule syntax in the docs first.
   4. **T1:**
      - write `docs/timeline-export.md`;
      - fix the doc drift from findings #3 and #11;
      - record that the current mobile tabs are interim.
   5. **T3:**
      - raise the Vite dev container's memory limit;
      - make the browser smoke test clean up its import batch;
      - hide the desktop search box until it's wired up.
   6. **Finding #12:** pin the Python, Node, and PostGIS base images to exact versions at least 14 days old.
   7. **T46:**
      - Make the permission matrix stop rebuilding its fixture for every case, without weakening anything: all 315 cases must still run and pass.
      - Mark slow tests with a `slow` marker and add a quick-suite command that excludes them.
      - Report before and after timings.
   8. **Finish:** full suite, lint, and type checks green; commit and push.
2. **[X] T4 + T2:** account privacy, and the database-backed rate limiter. Tests must cover concurrent requests.
   - Status: done (2026-11-11)
3. **[M] T5:** a 500 MB–1 GB synthetic import test. Record time, peak memory, and database growth. If it's over budget or fails: ESCALATE.
   - Status: done (2026-11-17). 1 GB passes: worker peak 272 MiB of 1,536; import 16 min; +1.24 GB DB, about 347 B/point. Re-run with `./dev import-scale-test`.
4. **[H] T11 re-planned: real data out of the dev stack.** Adam imported his Timeline through the dev app on 2026-11-18 (batch 33, 193,009 points), so there is nothing left to import. The count check and the backup moved to 40b, and the synthetic-data wipe became 40b's pruning of the production copy.
   - Preconditions, all checked first:
     - 40c's handover is verified;
     - a production backup has run (G-2);
     - production's raw-file checksums match the dev originals;
     - Adam approved G-6 (deleting real data is on CLAUDE.md's stop-and-ask list).
   - Reset the dev DB volume and delete the dev bulk directory's contents (`var/bulk`, D-84), so dev holds synthetic data only again (D-67's intent). Never touch `data/private/`.
   - Afterwards: `./dev up`, migrations, `./dev e2e`, the quick suite and `./dev restore-test` pass on the empty dev stack. The mock `dev-admin` login now opens an empty account.
   - Status: todo (re-planned 2026-11-18; PROPOSED: needs G-6)
5. **[H] T6:** raw-history map. ← my history becomes viewable
   - Status: done (2026-11-11)
   - **5a. [H] T6 follow-ups:**
     - a per-day grid roll-up so z0–6 tiles stay fast with millions of points;
     - a spatial key for segment tiles;
     - make the e2e upload check verify its own upload, not an earlier one.

     Run after item 3 has measured tile timings at 500 MB–1 GB. Then run `./dev restore-test` once the disk is fixed, to confirm the generated `tile_key` column restores.
     - Status: done (2026-11-18)
6. **[X] T18 core:** the permission-critical trips API, with endpoint tests for every role and visibility rule.
   - Status: done (2026-11-11)
7. **[X] T7:** tracker endpoints, built and tested locally.
   - Status: done (2026-11-16)
8. **[X] Tracker exposure, under all of these conditions:**
   - Route only the tracker paths. Every other path on that hostname returns 404 at the proxy until go-live.
   - The exposed service runs with production settings: DEBUG off, allowed hosts set, HTTPS only, HSTS, security headers.
   - Before exposure, all of these are in place:
     - the T2 rate limiter on these paths;
     - per-device write-only tokens, hashed at rest and revocable;
     - a request size cap and strict schema validation;
     - plausibility flags for impossible speeds or jumps;
     - responses that return no data;
     - logs that never contain tokens.
   - Use the same public path my existing sites use. If it passes through Cloudflare's proxy or Tunnel, say so, because Cloudflare can then see the location payloads in transit.
   - Show me the proxy change and the exact DNS record, and apply the change only after I reply "go". I add the DNS record myself.
   - Test from outside the LAN with a test token, then revoke it.
   - Walk me through setting up my phone with the setup guide and QR code. ← the bake-off starts
   - Status: on hold (Adam, 2026-11-19). The route is live and the outside test passed, including revocation. Colota's posts are refused (400 "_type missing": Colota apparently isn't sending OwnTracks format; Adam hasn't checked its Request format setting). The ingest service is stopped. To resume: check Colota's format, fix the parser if needed, then deploy the production stack's `ingest` (40a moves it there), so points land in production. 40d fixes the smoke test's expectations for Cloudflare's robots.txt and 404s. Device tokens carry over in 40b's copy.
9. **[H] T8:** nightly jobs that cover all users under RLS.
   - Status: done (2026-11-18)
10. **[M] T12 + T13:** flight datasets, the import template, and the conversion. Use my spreadsheet if it's present; otherwise synthetic data.
    - Status: done (2026-11-19, synthetic data; Adam's spreadsheet not yet provided)
11. **[M] T14 + T15:** flights on the map, grouping into trips, and dedupe against Timeline. ← my flights become viewable
    - Status: todo
12. **[M] T10:** coverage report, without the trip comparison.
    - Status: todo
    - **→ Review pause A:** history, flights, and tracking are live. I'll try them.
13. **[H] The rest of T18:** tags, stops, notes, media, tracks, the routes listing, bulk edit, duplicates/join/merge, leg reorder and list filters. Make sure a removed participant can no longer edit or delete their notes and tracks, matching the leg rule from item 6. Apply Adam's answer to Q-16.
    - Status: done (2026-11-19)
14. **[M] T26 part 1: GeoNames gazetteer and finding a stop by city name.** Adam's priority, 2026-11-18.
    - **Loader:** GeoNames populated places, plus country and admin-1 names, from a pinned, SHA-256-checked download with a generic User-Agent. Follow item 10's reference-data pattern (`DatasetVersion`, cache in `/bulk/reference`, D-88).
      - Start from cities500 worldwide. Small US towns matter (Kansas), so consider the US populated places below 500 people if disk allows, and record the sizes.
      - A trigram or prefix index; `pg_trgm` is a trusted extension, so the owner role can create it in a migration.
    - **API:** `GET /reference/places?q=`, the same shape and limits as `GET /reference/airports`, ranked by population, with admin-1 and country. Behind the login wall. Nothing leaves the server (D-20, rule 13).
    - **UI:** a "find a city" option in the stop editor, beside map click, airport and coordinates (D-90 (5), frontend-patterns.md). The chosen place fills the stop's name and point. Both shells.
    - **Credits:** CC BY 4.0 on the About page; licenses.md, facts register, phases.md 6.1 (partial).
    - **Tests:** the loader on a SYNTHETIC fixture, ranking and limits, API auth, the picker. The e2e adds a stop by city name.
    - **Out:** Natural Earth, Census counties and reverse geocoding (item 14a).
    - Status: todo
    - **14a. [M] T26 part 2: Natural Earth and Census boundaries + offline reverse geocoding.**
      - Natural Earth admin-0/1 and Census county loaders, same pattern as item 14.
      - Stops named offline ("near <town>, <state>", phases.md 6.1, D-20).
      - Runs before item 28 (territories), which needs the boundaries.
      - Status: todo
15. **[H] T9:** home-period detection.
    - Status: todo
16. **[M] T9:** the review UI and manual entry.
    - Status: todo
17. **[M] T17:** Valhalla with a Kansas extract. Check free disk first.
    - Status: done (2026-11-19)
18. **[X] T20 core:** trip detection and data integrity, including the locking of confirmed trips.
    - Status: todo
19. **[H] T20:** the review queue.
    - Status: todo
20. **[H] T19 session 1:** catalog UI architecture plus `docs/design/frontend-patterns.md`.
    - Status: done (2026-11-19)
21. **[M] The rest of T19,** following the patterns doc (2 dispatches).
    - Status: todo
    - **→ Review pause B:** the desktop catalog UI.
22. **[M] T20 polish,** plus the T10 trip comparison.
    - Status: todo
23. **[H] T21:** vehicles.
    - Status: todo
24. **[M] T22:** map-matched routes.
    - Status: todo
25. **[M] T23 + T24:** routing proxy and manual trips. Without an ORS key, use Valhalla only and leave the ORS fallback stubbed.
    - Status: done (2026-11-18)
26. **[H] T25 core:** the drag editor, ported from gpx.studio (MIT, with attribution).
    - Status: done (2026-11-18)
27. **[M] T25 polish:** item 26's leftovers.
    - an anchor popup;
    - touch;
    - `Route.sources` in the version list;
    - re-proposing expired spans instead of resending them as drawn points.

    It runs before Review pause B, which reviews the desktop catalog including the route editor.
    - Status: todo
28. **[H] T27:** territory stats.
    - Status: todo
29. **[M] T28:** distance and flight stats.
    - Status: todo
30. **[M] T29:** mobile features. Decide the final mobile tabs here.
    - Status: todo
31. **[H] T31:** basic photos. Tests must prove no EXIF, XMP, IPTC, maker notes, or HEIC metadata survive.
    - Status: todo
32. **[M] T30 + T32:** PWA polish (needs Q-8), plus upload docs and bearer-token photo upload.
    - Status: todo
33. **[H] T34:** roles and contributions.
    - Status: todo
34. **[X] T35:** the merge tool.
    - Status: todo
35. **[H] T36:** transfers.
    - Status: todo
36. **[X] T33 core:** request access, the auth flows, and abuse protection.
    - Status: todo
37. **[H] The rest of T33.**
    - Status: todo
38. **[X] T37 core:** the public snapshot builder, privacy-zone clipping, consent, and leak tests.
    - Status: todo
39. **[H] The rest of T37.**
    - Status: todo
**Family go-live slice (40a–40e, 41a, 42a; planned 2026-11-18).**
- **Goal:** Adam and a few family members sign in at https://travel.adamcasada.com through Authentik with 2FA and add trips.
- **Adam's decisions:**
  - trips.adamcasada.com redirects to travel.adamcasada.com;
  - Adam creates family accounts in Authentik (group `travel-users`), and they become Members;
  - request access (T33) stays later;
  - dev-admin's data moves to Adam's real account.
- **What waits until after go-live, and why:**
  - Items 36–37 (T33), apart from the account-to-person link pulled into 40c: Adam makes accounts himself.
  - Items 38–39 (T37) and the §6.5 snapshot allowlist: no public renderer routes (`/t/`, `/u/`, `/pm/`) exist. 41a confirms the anonymous surface is only the landing page, auth, SPA static files, `/healthz` and the ingest paths, and trips stay unpublishable until T37.
  - The rest of T38 (item 40).
  - The full review (item 41).
- **What can't wait:** all of auth.md §7.7 is in 40a.
- **Why a separate production stack (G-1):** today one Postgres holds Adam's real data and also takes the builders' WIP migrations (`./dev up` migrates from mounted code), the test databases, the e2e and scale-test writes, and the restarts. Its dev web is DEBUG runserver, and anyone on the LAN can sign in at the mock provider as `dev-admin`. Family data must never share that.
- **How real data moves:** a dump and restore of the whole dev DB into production's empty DB, then pruning the copy. This beats a per-user export or re-entering trips, which would need new code and lose the hand-entered trips.
- **Why the handover rebinds the identity instead of moving rows:** raw points and raw files reject UPDATE (D-49), so ownership can't move row by row. Keeping the old account id leaves every row in place.

40a. **[X] Production stack, separate from dev (PROPOSED: G-1).**
   - **Project:** its own compose project (e.g. `travel-history-prod`) with:
     - its own DB volume;
     - `.env.prod` (0600; freshly generated DB passwords and secret key; Adam adds the OIDC secret and `AGE_RECIPIENT`);
     - a bulk directory outside the git working tree, so `git clean` can't reach it. It sits on the SSD for now and moves to the new HDD together with D-84's move.
   - **Deploys:** only from a clean, pushed `main`, with the image tagged by commit. Add `./dev prod deploy|migrate|manage|psql|logs|ps|backup-now|restore-test|smoke`. Migrations run as the owner.
     - No source mounts, runserver, mock OIDC, Mailpit or Vite.
     - No dev command reaches the prod DB.
   - **Services:**
     - web: gunicorn plus the production SPA build, on `127.0.0.1:8784` only, with no LAN binding;
     - worker;
     - backup: unchanged, so it refuses to run without `AGE_RECIPIENT`;
     - `ingest`: moves here, profile `tracker`, and stays stopped while tracking is on hold.
   - **Hardening:** auth.md §7.7 complete, enforced at startup like `ingest` (D-85 (3)):
     - DEBUG off, explicit ALLOWED_HOSTS;
     - behind the TLS proxy, with SSL redirect and secure cookies;
     - HSTS once the scope is `all`;
     - CSP, nosniff, Referrer-Policy;
     - `RATELIMIT_CLIENT_IP_HEADER=CF-Connecting-IP`;
     - per-IP rate limits on `/auth/login`, `/auth/callback` and `/`.
     - `TRAVEL_PUBLIC_SCOPE` stays `tracker` until 40e.
   - **trips.adamcasada.com:** answers a permanent redirect to the same path on travel.adamcasada.com. It is app-level, tested, and not an open redirect; ingest paths are unaffected.
   - **Dev:** the dev stack can never answer a public host name (verify the DEBUG guard; empty dev `TRAVEL_PUBLIC_HOSTS`).
   - **Landing page:** offers only "Sign in" until item 36.
   - **Memory:** measure free RAM with both stacks, Authentik and Valhalla running. Set production memory caps and record them in resource-budget.md §21.
   - **Tests:** unsafe production settings refuse to start; the redirect; the auth-route rate limits; `./dev prod smoke` (headers, every private path refused anonymously) against the empty stack.
   - **Docs:** the builder records the decision (stack, port, bulk location) as pending Adam. Must not touch the dev DB or its data.
   - Status: todo
40b. **[X] Move the real data into production: tool and rehearsal (PROPOSED: G-2 for the backup gate).**
   - **Command:** `./dev prod import-from-dev`, repeatable and run as the owner role.
     - It refuses if the two DBs' applied migrations differ, and forever once any production account has a real (Authentik) identity.
     - It replaces production's DB with a dump of dev's, piped with no dump left on disk.
     - It copies the raw-archive files that surviving rows reference into production's bulk directory, verifying each SHA-256.
   - **Pruning, on the copy only (the dev original is untouched until item 4):**
     - every account except `dev-admin` (`dev-member`, `dev-outsider`, scale-test or e2e throwaways), with all their rows;
     - `dev-admin`'s synthetic rows: batches from SYNTHETIC fixtures, item 10's synthetic flight records, e2e leftovers;
     - sessions, the job queue, rate-limit counters and the routing cache.
     - It prints a dry-run inventory per account and table first.
     - It keeps batch 33, Adam's trips, legs, stops, persons and route versions, tracker points and device tokens, and the reference data.
   - **Verify:** `dev-admin`'s per-table counts equal dev's; batch 33 has 193,009 points; policy and `app` function counts match; raw checksums pass.
   - **Backup:** with `AGE_RECIPIENT` set, `./dev prod backup-now` writes an encrypted backup with the real data, and the throwaway-key restore test passes against production. Without the key, finish everything else and leave this gate open.
   - **Tests:** the tool against scratch containers with SYNTHETIC data, including pruning and refusals.
   - **Rehearsal only:** the final copy runs in 40c, right before Adam signs in, so whatever he enters in dev until then carries over.
   - Status: todo
40c. **[X] Authentik sign-in and the account handover (PROPOSED: G-3, G-4, G-5).** Two dispatches.
   - **Dispatch 1 [X]: build.**
     - **Authentik:** point production at Authentik per auth.md §7.2 (per-provider issuer, confidential client, `travel-users` group check, `auth_time`, end-session logout). Prove discovery and JWKS work from inside the prod web container through the public hostname; D-57's back channel is dev-only.
     - **Tests:** Authentik-shaped claims (issuer with a trailing slash, `email_verified=false`, group lists, a missing group refused, `auth_time`); the `amr` second-factor check (G-5).
     - **Pre-exposure sign-in:** make it work over an SSH port-forward to `localhost:8784` (G-4), without weakening the public-host settings.
     - **`rebind_identity`:** owner role only, dry-run by default, one transaction, logged.
       - It moves the Authentik identity (issuer, sub, email, name) of a brand-new account that owns nothing onto the existing account, then deletes the empty account and both accounts' sessions.
       - It refuses in every other case, and never matches by email.
     - **`link_person <account> <person>`:** owner role, like `set_role`. It links a family member's new account to the person Adam already put on trips. This slice of T33's onboarding (auth.md §7.3) is pulled forward because trips default to `participants` visibility (§6.2): unlinked, family members can't see the trips they're on.
     - **Command tests:** RLS-level: rows untouched, sessions gone, every refusal.
     - **Final copy:** run 40b's final copy after the orchestrator confirms Adam has stopped entering data in dev. Then end BLOCKED-ON-USER: Adam's first sign-in.
   - **Dispatch 2 [H]: after Adam signs in.**
     - Run `rebind_identity`, dry run first.
     - Adam signs in again and confirms he sees his history and trips; the counts are unchanged; his account is Admin.
     - Production now refuses `import-from-dev`.
   - Status: todo
40d. **[M] Minimal go-live runbook and outside smoke test (the go-live slice of T38).**
   - **`docs/go-live.md`, for Adam:**
     - Authentik checks (§7.2 items 1, 2, 5: group binding, forced second factor, strict redirect URI; remove G-4's temporary URI);
     - adding a family member: Authentik user → `travel-users` → second factor at first sign-in → Member → `link_person`;
     - the tunnel routes: travel.* and trips.* to `localhost:8784`, and what happens to the ingest path rule;
     - the DNS records;
     - the scope flip;
     - rollback: delete the route, set the scope back to `tracker`;
     - what Cloudflare can see.
   - **Smoke:** generalize `scripts/tracker-smoke.sh` into a go-live smoke covering:
     - anonymous refusals on every private path;
     - headers and HSTS;
     - the trips → travel redirect;
     - ingest unchanged;
     - the Cloudflare robots.txt and 404 expectations noted 2026-11-19.
     - Include a local mode that runs the production image with scope `all` on an unpublished port, so 41a can test the exact go-live configuration before the "go".
   - **Docs:** update phases.md 8.6 and docs/tracking/exposure.md for the production stack. The rest of T38 stays in item 40.
   - Status: todo
40e. **[H] Exposure, only after Adam's "go" and his tunnel change.**
   - Set production's scope to `all` (HSTS on) and redeploy.
   - Run the go-live smoke from outside the LAN.
   - Adam signs in at https://travel.adamcasada.com, and trips.* redirects.
   - Adam creates the first family account; it signs in as a Member and, linked, sees its trips.
   - Update PLAN.md, phases.md and the threat model's exposure row (D-73's tracker-only period ends).
   - Status: todo
40. **[M] The rest of T38:** the go-live checklist's SMTP, Turnstile, request-access and public-page parts, added to 40d's runbook.
    - Status: todo
41a. **[R] Focused security review of the app as it will be exposed (read-only).**
   - **Anonymous surface** on travel.* and trips.* with scope `all` (via 40d's local mode):
     - the login wall (D-56, §7.6);
     - no public-renderer or other unexpected routes;
     - the redirect isn't open;
     - error pages without DEBUG.
   - **OIDC against Authentik:**
     - state, nonce and PKCE;
     - issuer and audience checks;
     - `(iss, sub)` keying;
     - group refusal;
     - session rotation and cookie flags;
     - logout and re-auth;
     - the second-factor check.
   - **What a signed-in Member can reach:**
     - IDOR spot checks on trips, legs, stops, persons, route versions, uploads, history tiles and the routing proxy;
     - the account directory (D-72, D-76);
     - deactivated accounts;
     - Admin limits.
   - **Uploads:** limits, quota, archive handling.
   - **Routing proxy:** abuse, the ORS key, rule 13.
   - **Production stack:**
     - settings enforced at startup;
     - ports `127.0.0.1` only, DB unpublished;
     - non-root, capabilities dropped;
     - secrets: `.env.prod` mode, not in images, logs or git; gitleaks, and try Betterleaks (Q-12);
     - dependency CVEs (pip, npm, base images);
     - the dev stack unreachable through the tunnel, and whether dev's :8780 was reachable via travel.* before 2026-11-17 (NEXT.md).
   - **Handover result:** no mock identities or synthetic accounts in production; raw checksums; `rebind_identity`, `link_person` and `import-from-dev` owner-only and refusing correctly; the backup encrypted and restorable.
   - **Out of scope, left for item 41:** public pages, request access, trip detection, merge, transfers, photos. None of these exist yet.
   - **Output:** findings by severity. Blockers stop go-live.
   - Status: todo
   - **→ Pause:** 41a's findings summary, then ask for the exposure "go".
41. **[R] Full security and data-integrity review, read-only** (builds on 41a):
    - RLS, public routes, tokens, rate limits, headers, secrets, dependencies, leak tests;
    - the integrity of trip-detection locking (T20), the merge tool (T35), and transfers (T36).
    - Status: todo
    - **→ Pause:** the findings summary.
42a. **[H] Go-live blocker fixes from 41a.**
   - Skip this item if 41a finds no blockers.
   - Fixes to auth, RLS or the exposure guard are dispatched at [X].
   - Non-blocking findings go to item 43.
   - Status: todo
42. **[H] Blocker fixes.**
    - Status: todo
43. **[M] Other fixes.**
    - Status: todo
44. **[H] T39 session 1:** Android architecture plus a patterns doc.
    - Status: todo
45. **[M] The rest of T39.**
    - Status: todo
46. **[M] Optional, in order:** T16, T41, T42, T45.
    - Status: todo

**Later, only when I ask:**
- T40 Immich [X, then H].
- T43 bake-off conclusion [H], after 4–6 weeks of tracking data.
- T44 North America Valhalla build [H], after the Ryzen migration and with my approval.

## Task reference (from the 2026-10-21 audit)

Reference only: the work order above sets order, tiers and status. Folded in from the audit's STATUS.md on 2026-11-10 (Stage 0); PLAN §N references now resolve through the section map in PLAN.md.

### Tasks

Nature: mech = mechanical, mod = moderate, hard. Size is S/M/L/XL with approximate files and lines. "Conf" = confidence it fits one focused session.

| ID | Task (phase) | Size | Nature | Risk if wrong | Ambiguity | Depends on | Conf |
|---|---|---|---|---|---|---|---|
| T1 | Write `docs/timeline-export.md`; fix PLAN/CLAUDE drift (#3, #10–12) | S (3 files, ~120) | mech | low | settled | — | high |
| T2 | PostgreSQL rate limiter (`travel/core/ratelimit.py`) + tests (#2) | M (3 files, ~200) | mod | medium (abuse of public endpoints) | settled (D-10) | — | high |
| T3 | Raise Vite memory limit; e2e cleanup; hide or wire the search box (#5, #8, #9) | S (3 files, ~40) | mech | low | settled | — | high |
| T4 | Decide account-row visibility; restrict via a view or column grants (#6) | S–M (2 files, ~120) | hard (RLS) | medium (privacy) | **needs decision** | Adam (or accept a proposed default) | high |
| T5 | Realistic-size import test (500 MB–1 GB synthetic: time, RSS, DB size) (#4) | M (1 script, ~150) | mod | high if skipped (real import OOM or timeouts) | settled | — | high |
| T6 | 2.3 Raw-history map: points MVT (RLS, grid aggregation), segments overlay, date filter, coverage strip | M–L (~8 files, ~700) | mod | medium (privacy; RLS backs it) | settled (§14) | — | medium |
| T7 | 2.4 Tracker ingestion: OwnTracks/Overland endpoints, device tokens UI, QR/deep links (OwnTracks, Overland, Colota, GPSLogger), `docs/tracking/` | L (~12 files, ~1200) | hard | high (public write endpoints, tokens) | settled (§9) | T2 | medium |
| T8 | Design + implement cross-user periodic jobs under RLS (user enumerator function / per-user scheduling) | S–M (~3 files, ~150) | hard | medium | **not designed in PLAN** | — | high |
| T9 | 2.5 Home periods: night-location algorithm, suggestions, review UI, manual entry (map pin), gap/overlap validation | L (~10 files, ~1200) | hard | medium-high (feeds detection and privacy zones) | mostly settled (thresholds) | T6; address search needs T26 | low–medium (likely 2 sessions) |
| T10 | 2.6 Daily coverage job + bake-off page | M (~6 files, ~500) | mod | low | trip-comparison part needs 4.2 | T7, T8, (T20) | medium |
| T11 | Wipe synthetic dev data before the first real import (D-67) | S | mech | high (must touch dev data only) | settled | Adam's export | high |
| T12 | 3.1 OurAirports/OpenFlights loaders, `DatasetVersion`, attribution page | M (~5 files, ~400) | mod | low | settled | — | high |
| T13 | 3.2 Flight template, spreadsheet conversion script, date-aware code resolution, unmatched report | L (~6 files, ~800) | mod | medium (wrong airports) | mostly settled | T12; Adam's spreadsheet (synthetic first) | medium |
| T14 | 3.3 Great-circle arcs (antimeridian), flights on the map, trip grouping (trip key or auto-group candidates) | M–L (~6 files, ~600) | mod | medium | settled | T13 | medium |
| T15 | 3.4 Dedupe flights vs Timeline FLYING segments | S–M (~2 files, ~200) | mod | medium | settled | T13 | high |
| T16 | 3.5 Six other flight importers (MFR24, Flighty, App in the Air, TripIt, JetLog, byAir) | L (~8 files, ~900) | mod | low | formats medium-confidence | T13 | low (2 sessions) |
| T17 | 4.1 Valhalla compose project, Kansas tiles, backend client, `trace_route` wrapper | M (~5 files, ~400) | mod | low-medium (resources) | settled | — | high |
| T18 | 4.3a Trips/legs/participants/tags/stops API using `policy` + API-level permission tests | L–XL (~10 files, ~1500) | hard | high (permission leaks) | settled (§6, §17) | — | low (2 sessions) |
| T19 | 4.3b Desktop catalog UI: map home (trip MVT from `route_simplified`), list+map, filters, bulk edit, tags, participants, shortcuts | XL (~15 files, ~2000) | hard (UI) | medium | settled (§18) | T18 | low (2–3 sessions) |
| T20 | 4.2 Trip auto-detection (overnight, day trips, stay points, modes, legs, flight matching, fingerprints) + keyboard review queue | XL (~12 files, ~2000) | hard | high (data integrity, locked trips) | mostly settled; tune with real data | T9, T18, T13, (T17) | low (2–3 sessions) |
| T21 | 4.4 Vehicles: CRUD, ownership-history UI, "is it this one?" (SECURITY DEFINER plate match), merge, rental quick-add | L (~8 files, ~1000) | hard | medium (merge integrity, private fields) | settled | T18 | medium |
| T22 | 4.5 Map matching of drive legs (chunk, stitch, frozen route versions, simplified copies) | M (~4 files, ~400) | mod | medium | settled | T17, T20 | medium |
| T23 | 5.1 Routing proxy (Valhalla→ORS→FOSSGIS, OSRM normalization, throttle, cache, provenance) | M–L (~6 files, ~600) | mod | medium (ToS, personal data) | Q-9 open | T17, T2; ORS key (Adam) | medium |
| T24 | 5.2 Manual trip creation with proposed route | M (~5 files, ~500) | mod | low | settled | T23, T19 | medium |
| T25 | 5.3 Drag-to-reshape editor (gpx.studio MIT port, zoom anchors, undo/redo, save as new version) | XL (~8 files, ~1800) | hard (UI) | medium-high (rework) | settled (§13.4) | T23, T19 | low (2–3 sessions) |
| T26 | 6.1 Natural Earth, Census, GeoNames loaders + offline reverse geocoding | M (~5 files, ~500) | mod | low | settled | — | high |
| T27 | 6.2 Territories visited (through vs stopped-in; airports only for flights; cache + rebuild) | L (~6 files, ~800) | hard (geometry performance) | medium | settled | T26, T18, routes | medium |
| T28 | 6.3 Distances by vehicle/mode/year, flight stats, stats pages | M (~6 files, ~700) | mod | low | settled | T27, T21 | medium |
| T29 | 7.1 Mobile shell features (browse, filter, edit tags/participants/notes/contributions) | M–L (~8 files, ~800) | mod | medium | settled | T18, T19 | medium |
| T30 | 7.2 PWA polish (install, offline shell, iOS meta) | S–M (~4 files, ~200) | mech | low | Q-8 (HTTPS for testing) | Adam for HTTPS test path | high |
| T31 | 7.3 Basic photos: upload, Pillow re-encode, GPS/EXIF strip tests, thumbnails, limits, cover, protected serving, orphan sweep | L (~10 files, ~1000) | mod | high (GPS leak) | settled (§16.1) | T18 | medium |
| T32 | 7.4 Companion upload API docs + bearer photo upload | S–M (~3 files, ~200) | mod | medium | settled | T31 | high |
| T33 | 8.1 Request access: landing, form, Turnstile, rate limits, Web Push (VAPID), email, re-auth approve, provisioner stub, invites/QR, allowlist, onboarding | XL (~18 files, ~2000) | hard | high (abuse, account takeover) | mostly settled (§7.3–7.5) | T2; real keys later (Adam) | low (2–3 sessions) |
| T34 | 8.2 Roles + contributions UI (notes, photos, own legs, own tags, consent, own-leg participation) | L (~10 files, ~1200) | hard | high (permissions) | settled | T18, T19, T31 | medium |
| T35 | 8.3 Duplicate check / join / merge tool | L (~6 files, ~800) | hard | high (data integrity) | outline settled | T18, T34 | medium |
| T36 | 8.4 Transfers (bulk offers, SECURITY DEFINER accept, vehicles) | M–L (~6 files, ~700) | hard | high (ownership) | settled | T21, T34 | medium |
| T37 | 8.5 Public trips/profiles: snapshot builder, `travel_public` renderer, privacy-zone clipping, consent, noindex, rate limits, sentinel leak tests | XL (~14 files, ~1800) | hard | **high (privacy leak)** | settled (§6.5) | T2, T9, T18, T31 | low (2 sessions) |
| T38 | 8.6 Go-live checklist doc | S (1 file, ~150) | mech (careful) | medium | settled | T33, T37 | high |
| T39 | 9 Android companion (Kotlin, AppAuth, UIDT/WorkManager resumable uploader, share target, trip picker, Docker build, signing) | XL (new project, ~3000) | hard | medium | settled (§19.1) | T32; Authentik for real use | low (3+ sessions) |
| T40 | 10 Immich integration (encrypted per-user keys, SSRF rules, suggestions, thumbnail proxy, stripped public copies) | L–XL (~10 files, ~1200) | hard | high (credentials, SSRF) | settled (§16.2) | Adam's Immich | medium |
| T41 | 10 Tauri desktop wrapper | M | mod | low | settled | T19 | medium |
| T42 | 10 Regional PMTiles basemap | M | mod | low | needs OK on storage | — | medium |
| T43 | 10 Bake-off conclusion | S | analysis | low | — | 4–6 weeks of T7/T10 data | high |
| T44 | Full North America Valhalla build | M (ops) | mod | high (resources) | Q-4 | Adam approval; Ryzen or VM | medium |
| T45 | Optional: backend type checking (mypy + django-stubs) (#13) | M | mech | low | — | — | medium |
| T46 | Optional: faster tests (module-scoped scenario fixture; mark the memory test slow) | S–M | mod | low | — | — | high |

### Audit findings

| # | Finding | Paths | Severity |
|---|---|---|---|
| 1 | **Migration history rewritten after commit.** All initial migrations were regenerated in 57e9a01 (DB-level `on_delete`), and the RLS migration was edited in 8ea6efa. A DB built at an earlier commit can't migrate forward. The dev DB was reset, so the current state is consistent. | `backend/travel/*/migrations/0001_initial.py`, `core/migrations/0002_row_level_security.py` | cosmetic now; blocker if it ever happens after real data. Add a "never edit applied migrations" rule |
| 2 | **Rate limiter missing.** It is planned in D-10, §9.1 and §20, but `travel/core/ratelimit.py` doesn't exist and the `RateLimitBucket` model is unused. CLAUDE.md lists `ratelimit` as part of core. Needed before ingestion (2.4) and public routes (phase 8). | `backend/travel/core/`, `CLAUDE.md` | fix soon |
| 3 | **Broken doc link.** The phase-0 checklist links `docs/timeline-export.md`, which doesn't exist; the export steps are only in the History page. Also referenced but not yet built (future phases): `docs/tracking/`, `docs/flights/template.csv`, `data/fixtures/flights_synthetic.csv`. | `PLAN.md` §23 | fix soon (S) |
| 4 | **2.2 acceptance criterion loosened.** It required "a 1 GB synthetic file stays under the worker limit". The test instead compares ~3.5 MB and ~14 MB files and checks that peak memory stays flat. No realistic-size import (hundreds of MB) has been run, so real-scale time and memory are UNVERIFIED. | `backend/tests/test_timeline_import.py`, `PLAN.md` §23 | fix soon (before the first real import) |
| 5 | **Vite dev container at 82% of its memory limit.** Risk of an OOM kill. | `compose.dev.yaml` | fix soon (S) |
| 6 | **Every account row is readable by the whole family.** The `accounts_user` SELECT policy lets every family member read every user row, including email and OIDC subject, at the DB level. The API exposes only `/me` today. PLAN doesn't decide this. | `core/migrations/0002_row_level_security.py` | fix soon (decide before 8.2 lists users) |
| 7 | **Policy layer is ahead of the API.** 20 of 24 functions in `travel/core/policy.py` have no caller outside tests, because no trip, vehicle or home endpoints exist yet. Same for `has_recent_auth` and the frontend notifications adapter and `canWatchFolders`. This is planned code, not dead code, and nothing tests it at the API level. | `travel/core/policy.py`, `frontend/src/platform/*` | cosmetic (track) |
| 8 | **e2e leaves data behind.** Each smoke-test run leaves a duplicate import batch in the dev DB (8 so far). | `e2e/smoke.mjs` | cosmetic |
| 9 | **Desktop search box does nothing.** It has no handler. | `frontend/src/shells/DesktopShell.tsx` | cosmetic |
| 10 | **Mobile tabs drift from the plan.** The tab bar is Map/Trips/History; PLAN §18.3 says Map/Trips/Add/Me. | `frontend/src/shells/MobileShell.tsx` | cosmetic (PLAN drift) |
| 11 | **D-23 wording is wrong.** It says tests use `SET LOCAL ROLE`; the code uses `SET ROLE` with `RESET ROLE` on teardown. | `PLAN.md` §24, `backend/tests/conftest.py` | cosmetic |
| 12 | **Image tags aren't fully pinned.** CLAUDE.md says they are, but `python:3.13-slim-trixie`, `node:24-trixie-slim` and `postgis/postgis:18-3.6` are moving tags without digests. | `compose*.yaml`, Dockerfiles | cosmetic |
| 13 | **No backend type checking.** The conventions call for type hints, but nothing checks them. | `backend/` | cosmetic |
| 14 | **Duplicated or abandoned code: none found.** Each concern has one implementation. The resume-notes file and a stray file were removed before the first commit. | — | — |
| 15 | **Broken commits:** HEAD is verified green. Intermediate commits weren't re-tested (UNVERIFIED); each milestone message claims a green run. See #1 for migration incompatibility between commits. | — | cosmetic |
| 16 | **Permission tests that don't exist yet.** The matrix (45 actions × 7 actors) covers the RLS and policy layers, and the upload, import and preferences endpoints have API-level tests. Missing, because the features don't exist: API-level tests for trips, legs, vehicles and homes; public-page leak tests; ingestion-token tests. | — | track (each must land with its feature) |

## Changelog
- 2026-11-10: item 1 done and verified (commits pushed, tree clean, `./dev test-quick` 432 + 18 passed; builder-medium confirmed running Opus 5.5 at medium effort).
- 2026-11-11: item 2 done and verified (pushed, tree clean, `./dev test-quick` 512 + 18 passed; builder-xhigh confirmed running Opus 5.5 at xhigh).
- 2026-11-11: item 3 blocked because the /bulk HDD is failing (read-only, I/O errors); item 4 deferred. Skipping ahead to item 5, which doesn't write to /bulk.
- 2026-11-11: item 5 done and verified (pushed, tree clean, `./dev test-quick` 601 + 26 passed; builder-high confirmed at high; RLS migration 0007 checked: same conditions, evaluated once per statement). Added fix item 5a for low-zoom scaling, segment tile key and the e2e upload check, gated on item 3's measurements.
- 2026-11-11: item 6 done and verified (pushed, tree clean, `./dev test-quick` 1072 + 26 passed; builder-xhigh at xhigh). Item 13 now lists item 6's leftovers, including aligning note/track rules for removed participants. D-81 and Q-16 are waiting for Adam.
- 2026-11-16: item 7 done and verified (pushed, tree clean, `./dev test-quick` 1245 + 31 passed; builder-xhigh at xhigh). It was interrupted by the usage limit and resumed. D-82 and Q-17 are waiting for Adam.
- 2026-11-17: Adam approved D-81, D-82, D-83 (item 5 tiles), the D-76 directory fields, Q-10, Q-12, Q-16 and Q-17. Item 3 is unblocked by D-84 (bulk on the SSD while the HDD is replaced). Item 8 is dispatched to prepare only.
- 2026-11-17: item 8 prepared and verified (pushed, tree clean, `./dev test-quick` 1260 + 31 passed; the ingest service on 127.0.0.1:8783 returns 404 off the ingest paths and sends HSTS and security headers). Waiting for Adam's "go". Item 3 dispatched meanwhile.
- 2026-11-17: item 3 done and verified (`./dev test-quick` 1260 + 31 passed). The builder lost Bash access at its last step, so the orchestrator committed its docs. Finding #4 is closed. The tiles confirm item 5a is needed: whole-history point tiles take 1–2 s at 3.6 M points. Point storage is about 347 B per point, so 20 M points would be about 7 GB against a 5 GB budget; the budget note is in resource-budget.md §21.1. Item 5a dispatched.
- 2026-11-18: item 5a done and verified (`./dev test-quick` 1375 + 31 passed, now about 3.3 min). Whole-history tiles take 50–274 ms; the cost is +37 % import time and +36 % point storage (about 9.3 GB at 20 M points). D-86 is waiting for Adam. Item 8 still waits for "go", so item 9 was dispatched.
- 2026-11-18: item 9 done and verified (`./dev test-quick` 1394 + 31 passed). D-87 (the per-user job runner) is waiting for Adam. Item 10 dispatched with synthetic flights.
- 2026-11-18: reordered at Adam's request: items 13, 20 and 21 run right after item 10, so he can add and browse trips sooner. T19 depends only on T18, so no dependency is broken. Item 4 jumps the queue when its prerequisites arrive.
- 2026-11-18: Adam approved item 8 ("go"). Its last step runs right after item 10.
- 2026-11-19: item 10 done and verified (`./dev test-quick` 1523 + 32 passed; the dev stack was restarted to pick up new packages). D-88 is waiting for Adam. The tunnel route isn't in place yet (travel.adamcasada.com answers 404 from Cloudflare), so item 8's last step waits for Adam's dashboard change and item 13 runs now.
- 2026-11-19: tunnel route live (Adam). The outside smoke test passed except two Cloudflare-side items: its managed /robots.txt answers 200, and Cloudflare's own 404s carry no app headers because the path rule never forwards those paths. Fix the smoke script's expectations in a later fix item. At Adam's request, added trips.adamcasada.com as a second public host (`.env` TRAVEL_PUBLIC_HOSTS; ingest recreated; it answers like travel.*). Adam adds its tunnel route. TRACKER_BASE_URL stays travel.*. Before go-live (T38), pick one canonical host for the web app (Authentik redirect URIs, one login) and redirect the other.
- Item 4 note: the synthetic-data wipe must keep the phone's tracker points and tokens (stored under dev-admin until Authentik is live).
- 2026-11-19: item 13 done and verified (`./dev test-quick` 2044 + 32 passed; matrix 665 cases). D-89 is waiting for Adam. Reordered at Adam's request so manual trips with road routes come sooner: 20 → 21 → 17 → 25 → 26. Tracking is on hold and the ingest service is stopped.
- 2026-11-19: item 20 done and verified (`./dev test-quick` 2117 + 72 passed; e2e covers creating, editing and deleting a trip). Adam can now enter trips, stops, legs and people. D-90 is waiting for Adam. Moved item 21 after 26, because item 20 already covers manual entry and Adam's priority is road-routed legs. Item 17 dispatched.
- 2026-11-19: item 17 done and verified (Valhalla 3.9.1 healthy, the orchestrator's smoke test passed, `./dev test-quick` 2125 + 72 passed). D-91 is waiting for Adam. Item 25 dispatched; there's no ORS key yet, so the ORS path is built and tested against mocks and goes live when `ORS_API_KEY` appears.
- 2026-11-18: item 25 done and verified after resuming from the usage-limit checkpoint (pushed, tree clean, `./dev test-quick` 2199 + 78 passed; e2e routes and saves a Kansas leg through Valhalla). ORS is built and mock-tested and goes live when `ORS_API_KEY` is set and web/worker restart. D-92 was recorded by the builder; it waits for Adam like D-89–91. Item 26 dispatched.
- 2026-11-18: Adam added ORS_API_KEY to .env. Web/worker recreated after Adam's import finished; a Denver→Boulder test route came back from ORS (46 km). ORS is live.
- 2026-11-18: Adam asked to move Authentik/go-live up so he and his family can start adding trips. After item 26 reports, dispatch the planner to plan a minimal family go-live slice next (prod web service, real Authentik OIDC, hardening §7.7, focused security review, exposure on Adam's "go"). Adam's answers (defaults): public at travel.adamcasada.com behind Authentik 2FA (exposure still needs his explicit "go" and his tunnel change); he creates family accounts in Authentik and they become Members, request-access form stays later; a focused security review of the exposed app before go-live; item 26 finishes first.
- 2026-11-18: Adam started a real Google Timeline import through the app on the dev stack. Don't interrupt it: no restarts of web/worker/db until it finishes (this delays the ORS restart). The dev DB now holds real data, so item 4's "wipe synthetic data" step must be re-planned (no blanket wipe), and backups of real data need AGE_RECIPIENT. Builder of item 26 told to leave the stack alone.
- 2026-11-18: Adam prioritized item 14 (T26 places: GeoNames gazetteer, so stops can be entered by city name) to run right after item 26, then the family go-live slice. Don't interrupt item 26. The go-live plan must include moving dev-admin's data (imported history, trips, tracker points) to Adam's real Authentik account at his first sign-in. Order: 26 → planner (place 14 next, then go-live slice) → 14 → go-live items.
- 2026-11-18: item 26 done and verified (pushed, `./dev test-quick` 2224 + 103 passed; e2e drags an anchor and saves a hand-edited version). Adam's real import (batch 33, 193,009 points) checked intact afterwards. D-93 (saving edited routes) waits for Adam with D-89–92. Planner dispatched for the item 14 + family go-live re-plan.
- 2026-11-18 (planner): new execution order: 14 → 40a–40d → 41a → 42a → pause (findings + "go") → 40e → 4 → 21 → 27 → pause B → 11 → 12 → pause A → 15 … Reason: Adam's 2026-11-18 priorities (city search, then family go-live), with dependencies kept.
- 2026-11-18 (planner): split T26. Item 14 is now the GeoNames gazetteer and finding a stop by city name, which is Adam's ask. New 14a (Natural Earth, Census, reverse geocoding) runs before item 28, its only dependant.
- 2026-11-18 (planner): added 40a [X], a production stack separate from dev (PROPOSED: G-1). Reason: dev's DB takes WIP migrations, test DBs, e2e writes and restarts, and its dev web is DEBUG runserver with a mock login, so family data can't live there.
- 2026-11-18 (planner): added 40b [X], the data move into production (dump and restore of dev, then pruning the copy). Reason: the real import already happened in dev (batch 33), so a dump and restore keeps it and the hand-entered trips without new export code.
- 2026-11-18 (planner): re-planned item 4 [M → H] as removing the dev copy of the real data (PROPOSED: G-6). Reason: there's nothing left to import, a blanket wipe would destroy real data, and deleting real data needs Adam's approval.
- 2026-11-18 (planner): added 40c [X, then H], the Authentik sign-in and identity handover (PROPOSED: G-3–G-5). Reason: the OIDC client was tested only against the mock, and append-only points and raw files (D-49) rule out moving rows to a new account.
- 2026-11-18 (planner): pulled T33's account-to-person link forward into 40c as an owner-role command. Reason: trips default to `participants` visibility, so unlinked family members wouldn't see the trips they're on.
- 2026-11-18 (planner): added 40d [M], the minimal go-live runbook and smoke test (T38's go-live slice, plus the Cloudflare smoke fix from 2026-11-19); item 40 keeps the rest of T38. Reason: Adam needs a checklist for the tunnel change and adding family accounts now; SMTP, Turnstile and public pages come later.
- 2026-11-18 (planner): added 41a [R], a focused review of the exposed surface before go-live, and 42a [H] for its blockers; item 41 stays the full final review. Reason: Adam asked for a focused review before exposure.
- 2026-11-18 (planner): added 40e [H], the exposure after Adam's "go". Reason: exposure is a stop-and-ask step and needs his tunnel change.
- 2026-11-18 (planner): items 36–39 and the §6.5 snapshot allowlist stay after go-live. Reason: request access stays later (Adam), and no public renderer routes exist, so 41a only has to confirm the anonymous surface.
- 2026-11-18 (planner): moved item 27 (editor polish, scope from item 26's report) before Review pause B. Reason: pause B reviews the desktop catalog, which includes the route editor.
- 2026-11-18 (planner): batched questions G-1 to G-6 for Adam at the top of the work order, all PROPOSED with recommended defaults. Reason: the prod stack, the backup gate, the handover, the pre-exposure sign-in, the 2FA check and deleting the dev copy each need his approval.
