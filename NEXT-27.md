# NEXT-27 (lane 1, branch item/27)

Item 27 (T25 editor polish), frontend only, no backend/API/migration change.

- **Done:** anchor popup (remove / keep as fixed point; Escape or a click elsewhere closes), touch
  (drag anchors, tap for popup, hold the line 400 ms to grab, contextmenu after touch ignored),
  `Route.sources` in the version list (`routing/sources.ts`), expired proposals re-proposed via
  `/api/v1/routing/route` before falling back to drawn (`routing/editor/repropose.ts`, wired into
  `editorStore.save`). Tests: `controller.test.ts` (fake map), `repropose.test.ts`,
  `sources.test.ts`, store and page tests. e2e editor step opens the popup and checks the sources.
- **Docs:** routing.md §13.4 "Polish (item 27)", D-106 (decisions.md + PLAN.md index), phases.md 5.3.
- **At merge:** if lane 2 (21a) also took D-106, renumber this one to the next free number.
- **Not done / notes:** the editor still renders only in the desktop shell (`mode === "desktop"` in
  LegRoutePage); touch helps tablets and touch laptops, phones never load it (§18.1). Real-device
  touch testing hasn't happened (only unit tests with a fake map); Adam can try it at Review pause B.
