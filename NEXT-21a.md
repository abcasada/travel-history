# NEXT-21a

Lane 2 handoff for item 21a (the trip list as a working tool). Fold into NEXT.md at merge.

- **Status:** built and committed on item/21a; frontend only, no migration, no API change.
- **What's in:** `trips/selection.ts` (zustand cursor + selection, pure rules), `trips/BulkBar.tsx`
  + `trips/bulk.ts` (tag incl. new tag, purpose with 1-7, people, visibility; 403 refusals
  listed), paging with `useInfiniteQuery` ("Show N more"), person and visibility filters,
  `shells/HeaderSearch.tsx` (desktop, `/`), map highlight of selection + cursor and `f` fit
  (`map/TripLayers.tsx`, `tripBounds` takes several ids), shortcut help rows, shortcut adapter
  tweaks (checkbox focus, Enter on links/buttons, bare Shift). Docs: frontend-patterns.md §8,
  ui.md §18.4 note, phases.md 4.3.
- **Left out:** the trip status filter. The OpenAPI schema names `Trip.Status` and
  `FlightRecord.Status` both "Status", so the generated type is `resolved | unmatched` (the
  backend actually validates `candidate | confirmed`). Fix item: rename the trip enum in the
  schema (e.g. `TripStatus`), regenerate, then add the filter. Candidates only exist from item 19.
- **Tests:** see the final report / commit log (Vitest: TripListBulk, HeaderSearch, selection,
  filter, geo, shortcuts; e2e step "list as a working tool").
