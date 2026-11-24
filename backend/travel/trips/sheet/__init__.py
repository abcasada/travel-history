"""Trip spreadsheet import (docs/design/trip-sheet.md §28, D-95).

reader  .xlsx limits and raw cells (openpyxl, read-only, XML through defusedxml)
layout  the blocks of a tab: trip fields, stops header and rows, legs header and rows
values  cell parsers: local times, zones, stop references, modes, keys
resolve places (gazetteer, airports, coordinates), zones, people, purposes, tags, vehicles
parse   one tab -> normalised content + issues; the whole workbook
plan    outcome per tab against the caller's trips (new, update, identical, review, ...) + diff
commit  writes through travel.trips.services as the caller, one savepoint per tab
importer the `trip_sheet` import kind (worker step) and the CSV report
"""
