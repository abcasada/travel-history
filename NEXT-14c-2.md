# NEXT-14c-2 (lane 2, branch item/14c-2)

- **State:** frontend in `frontend/src/imports/` (paths, sheet.ts logic, ImportsPage, TripSheetPreviewPage, TabCard, SheetLayers) wired into routes, MapLayers, ShellMenu and the trip list; Vitest tests green (28 new). e2e step + SYNTHETIC fixture `e2e/fixtures/trip-sheet-synthetic.xlsx` (built by `scripts/make_e2e_trip_sheet.py`).
- **Next:** run the lane stack (`./dev up && ./dev load-reference`), `./dev e2e`, then docs (frontend-patterns, trip-sheet §28.12), quick suite, `./dev down`.
