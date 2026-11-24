# NEXT-14c-1 (lane 2, branch item/14c-1)

Item 14c-1 (trip spreadsheet importer, backend) done 2026-11-24; fold into NEXT.md at merge.

- **Built:** `backend/travel/trips/sheet/` (reader with size/archive limits and a defusedxml
  check, layout, values, resolve, parse, plan, commit, importer, api), CLI `trips_sheet_import`
  (`--commit`, `--create-people`, `--recreate`), upload kind `trip_sheet` (≤ 10 MB) with the
  worker step ending at batch status `preview`, `GET /imports/{id}/trip-sheet`,
  `POST /imports/{id}/commit`, `POST /imports/{id}/discard`, `GET /trips/sheet-template.xlsx`.
  Migrations: history 0014 (kinds/statuses), trips 0008 (stop `time_precision`/`sheet_key`/
  `import_batch`, leg `sheet_key`, `tripsheetrecord` + `tripsheetlink` with own-only RLS and the
  record guard trigger). Services gained `in_app=False` / `provenance`. `defusedxml==0.7.1`
  added (the lane image was rebuilt; main's image needs a rebuild after the merge).
- **Decisions:** D-100 (identical bytes re-parsed unless their preview is open), D-101 (commit
  body: `seen` → 409, record-id lists `create_people` / `recreate` / `remove_missing`), D-102
  (how the importer writes). Renumber at merge if main has moved past D-99.
- **Matrix:** 108 actions × 7 actors (6 new rows); permissions.md §6.3 updated.
- **For 14c-2 (preview UI):** upload with the chunked API, kind `trip_sheet`; poll
  `GET /imports/{id}` until `preview` (or `failed`, `duplicate` → open `summary.duplicate_of_batch`);
  render `GET /imports/{id}/trip-sheet` (tabs: outcome badge, issues by row/column with
  `hint`/`candidates`, `diff`, `unknown_people` → unticked "create these people", `deleted` →
  unticked "re-create", kept rows → unticked "also remove these"); commit with
  `seen = tabs.map(t => ({record_id, trip_updated_at}))` and handle 409 (`records`: preview
  again) and 422. Map layer from each tab's `stops`/`legs` (`[lon, lat]`). The CSV report is
  client-side (issue fields map to `tab,row,column,severity,reason,message,hint`). StopOut now
  has `time_precision`. Invalidate trips queries after a commit.
- **Open:** review flags' "apply the sheet version" waits for the review queue (item 19);
  flight legs from a sheet get no great-circle route until item 11; GeoNames alternate names
  still aren't loaded.
