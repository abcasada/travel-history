# NEXT-43a: small fixes (frontend and tooling), lane 1

Status: done (2026-11-24), awaiting the orchestrator's merge. Quick suite 2580 + 184 passed in
the lane, lint clean, e2e green with no unexpected console errors. No backend code, migration or
API change (the served template .xlsx under backend/travel/trips/sheet/ is regenerated data).

- **Lane rm** (scripts/lane.sh, docs/development.md): merged = ancestor of main, or every
  commit patch-equivalent in main (`git cherry`, for a rebase not written back to the branch);
  deletes with `git branch -D` (`-d` compared with the stale pre-rebase upstream) and removes
  `origin/item/<item>` if present. Tested in a scratch clone with a local bare repo as origin and
  a local-only main: rebased-in-worktree, rebased-on-a-copy, unmerged (refused; --force keeps
  the branch). Lane-specific scratch/log names: documented and printed by `lane new` (lane
  builders share the orchestrator's scratchpad). The builder agent files weren't edited (config);
  the orchestrator may want to add the naming rule to lane briefs.
- **Mobile search** (fe:trips): `TitleSearch` in TripFilters.tsx keeps local text through
  `trips/useFollowedText.ts`, now shared with HeaderSearch. TitleSearch.test.tsx fails on the
  old URL-bound box (checked) and passes now.
- **Template**: Instructions tab says "open the menu under your name, choose Import trips from a
  spreadsheet, then Upload a trip spreadsheet … chosen Import". Rebuilt with
  scripts/make_trip_template.py; the served backend copy is now a byte copy of the docs one (two
  saves differed by zip timestamps). SYNTHETIC markers kept.
- **Glyph 404: narrowly ignored, upstream gap.** The URL was
  `tiles.openfreemap.org/fonts/Noto Sans Regular/66560-66815.pbf` (U+10400-U+104FF, Deseret and
  Osage, used by some OSM names in the basemap). OpenFreeMap 404s that range for Regular and
  Bold while neighbouring ranges are 200; our own label layers already use a served font.
  e2e/smoke.mjs drops only that exact URL (both the response line and its console line).
- **Merge note:** `./dev lane rm 43a` after the merge exercises the new code for real.
