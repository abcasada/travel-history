# Roadmap

Only the orchestrator and the planner edit this file. Status values: todo · in progress · done · deferred · blocked.

## Work order
Tiers: [M] builder-medium, [H] builder-high, [X] builder-xhigh, [R] reviewer-xhigh. Task IDs are from the 2026-10-21 audit (STATUS.md, or ROADMAP.md if Stage 0 already ran). Each item is one dispatch unless noted.

1. **[M] Stage 0 housekeeping** (details below). Skip it if already done.
   - Status: todo

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
   - Status: todo
3. **[M] T5:** a 500 MB–1 GB synthetic import test. Record time, peak memory, and database growth. If it's over budget or fails: ESCALATE.
   - Status: todo
4. **[M] T11 + real import:**
   - Wipe the synthetic data, after confirming the target is the dev database and holds only synthetic data.
   - Import my real export and verify the counts.
   - Confirm a nightly backup has run that includes real data.
   - Needs `AGE_RECIPIENT` and my export; if either is missing, defer this item.
   - Status: todo
5. **[H] T6:** raw-history map. ← my history becomes viewable
   - Status: todo
6. **[X] T18 core:** the permission-critical trips API, with endpoint tests for every role and visibility rule.
   - Status: todo
7. **[X] T7:** tracker endpoints, built and tested locally.
   - Status: todo
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
   - Status: todo
9. **[H] T8:** nightly jobs that cover all users under RLS.
   - Status: todo
10. **[M] T12 + T13:** flight datasets, the import template, and the conversion. Use my spreadsheet if it's present; otherwise synthetic data.
    - Status: todo
11. **[M] T14 + T15:** flights on the map, grouping into trips, and dedupe against Timeline. ← my flights become viewable
    - Status: todo
12. **[M] T10:** coverage report, without the trip comparison.
    - Status: todo
    - **→ Review pause A:** history, flights, and tracking are live. I'll try them.
13. **[H] The rest of T18.**
    - Status: todo
14. **[M] T26:** places.
    - Status: todo
15. **[H] T9:** home-period detection.
    - Status: todo
16. **[M] T9:** the review UI and manual entry.
    - Status: todo
17. **[M] T17:** Valhalla with a Kansas extract. Check free disk first.
    - Status: todo
18. **[X] T20 core:** trip detection and data integrity, including the locking of confirmed trips.
    - Status: todo
19. **[H] T20:** the review queue.
    - Status: todo
20. **[H] T19 session 1:** catalog UI architecture plus `docs/design/frontend-patterns.md`.
    - Status: todo
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
    - Status: todo
26. **[H] T25 core:** the drag editor, ported from gpx.studio (MIT, with attribution).
    - Status: todo
27. **[M] T25 polish.**
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
40. **[M] T38:** the go-live checklist.
    - Status: todo
41. **[R] Security and data-integrity review, read-only:**
    - RLS, public routes, tokens, rate limits, headers, secrets, dependencies, leak tests;
    - the integrity of trip-detection locking (T20), the merge tool (T35), and transfers (T36).
    - Status: todo
    - **→ Pause:** the findings summary.
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

## Changelog
