# NEXT-14c-1 (lane 2, branch item/14c-1)

In progress (2026-11-24): trip spreadsheet importer, backend.

- Done so far: models + migrations (history 0014, trips 0008 with RLS and the record guard),
  services `in_app`/`provenance` options, `travel/trips/sheet/` (reader, layout, values, resolve,
  parse, plan, commit, importer, api), CLI `trips_sheet_import`, parser tests (51 green).
- Next: import/commit tests, permission tests (API + RLS as travel_app, matrix rows), docs
  (permissions §6.3, data-model, api.md, trip-sheet.md, decisions), openapi + client regen,
  quick suite.
