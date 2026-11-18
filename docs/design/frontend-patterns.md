# Frontend patterns

Written in work-order item 20 (T19 session 1, 2026-11-19; decision D-90, pending Adam). This is
how the catalog UI is built, so that later items (21, 25, 26, 30 and on) add pages the same way.
Read it before touching `frontend/src/`. Layout and shortcuts are in [ui.md](ui.md) (§18), the
endpoints in [api.md](api.md) (§17), the map's server side in [map-rendering.md](map-rendering.md).

## 1. Where things live

```
frontend/src/
  api/client.ts         apiFetch: the only fetch (cookie, CSRF, ApiError). Generated hooks call it.
  api/generated.ts      orval output. Never read or edit it; import hooks and types from it.
  api/errors.ts         errorKind / errorMessage / fieldErrors: what the UI says for each status
  auth/AuthGate.tsx     useMe(): the signed-in user (role, person_id)
  pages/routes.tsx      every list-pane route (both shells render it)
  shells/               DesktopShell (lazy chunk), MobileShell, ShortcutHelp
  map/                  BaseMap; MapLayers (everything drawn on the map); TripLayers;
                        HistoryLayers; MapPick (pick handler + view tracker); store.ts; geo.ts
  trips/                the catalog feature: paths.ts, filter.ts, labels.ts, cache.ts, pages,
                        editors (TripFieldsForm, ParticipantsEditor, StopsEditor, LegsEditor),
                        inputs.tsx (PlaceInput, AirportSearch, ZonedTimeInput)
  routing/              a leg's route view: LegRoutePage (list pane), LegRouteLayer (map) - the
                        slot for items 25-26
  ui/                   form.tsx (Field, Button, Section, inputClass), QueryState.tsx
  lib/time.ts           wall-clock time in an IANA zone <-> UTC, display helpers
  platform/             adapters (shortcuts, files, notifications): the only platform-specific code
  test/                 setup (MapLibre mocked), fetch.ts (stubFetch, ME), render.tsx (renderAt),
                        trips.ts (synthetic fixtures)
```

A new feature gets its own folder like `trips/` (pages, editors, `paths.ts`, `labels.ts`,
`cache.ts`), not more files in `pages/`.

## 2. Pages and routing

- **The URL is the state.** Which page, which trip, and every list filter are in the URL
  (`/trips?tag=5&mode=drive&mode=flight`, `/trips/12/edit`). The list pane and the map are separate
  React trees in the desktop shell (two panels), so they share state through the URL, not props.
  A filtered view can be bookmarked and the back button works.
- **Routes** are declared once in `pages/routes.tsx`; both shells render `<ListRoutes />` and
  `<MapLayers />`. Build links with `trips/paths.ts` (`paths.trip(id)`, `paths.edit(id)`,
  `paths.legRoute(tripId, legId)`), never string literals. `selectedTripId(pathname)` and
  `selectedLegId(pathname)` tell map layers what is open.
- **Filters** are read and written by a pure module (`trips/filter.ts`: `readTripFilter`,
  `writeTripFilter`, `apiParams`), like `history/filter.ts`. Write with
  `setParams(next, { replace: true })` so typing doesn't fill the history. Repeated parameters
  are any-of; the generated client sends arrays as `tag=1&tag=2` (tested in
  `trips/filter.test.ts`).
- **Route ids** come from `useParams`; an id that isn't a positive integer renders "doesn't
  exist" without a request (`useTripId()`).
- Desktop-only heavy pages (route editor, review queue, stats) must be lazy chunks reached only
  from the desktop shell (`React.lazy`), so phones never download them (§18.1).

### How to add a page

1. Add the path builder to the feature's `paths.ts`.
2. Write the page component in the feature folder. Load data with a generated hook; wrap the
   result in `<QueryState query={…} what="…">` (section 4).
3. Register it in `pages/routes.tsx`, next to the feature's other routes (React Router ranks
   `trips/new` above `trips/:tripId` by itself).
4. If it draws on the map, add a layer component to `map/MapLayers.tsx` that returns `null`
   unless the URL is one of its pages (section 5).
5. Add a nav link or a link from an existing page; keyboard shortcuts go through `useShortcuts`
   and get a row in `shells/ShortcutHelp.tsx`.
6. Tests: a `*.test.tsx` next to the page using `renderAt` (section 7); extend `e2e/smoke.mjs`
   if it's a main flow.

## 3. Server data, client state, forms

### Server data

- **Only generated hooks** (`useListTrips`, `useGetTrip`, `useCreateLeg`, …) and generated
  functions talk to the API. No `fetch`, no hand-written URLs (map tile URLs are the one
  exception: MapLibre fetches them itself).
- **Caching**: React Query, `staleTime` 30 s, no retry on 4xx (`App.tsx`). Lists that change
  with filters use `placeholderData: keepPreviousData` so they don't flash empty.
- **After a mutation, invalidate in one place per feature**: `trips/cache.ts`
  `useInvalidateTrip()(tripId)` refreshes that trip's detail, every trip list and the trip map.
  Editors call it in `onSuccess` and never patch cached data by hand (simple and always right at
  family scale). A new feature with its own lists gets its own `cache.ts`.
- Other queries' keys come from the generated `get…QueryKey()` functions (e.g. after
  `createMyPerson`, invalidate `getGetMeQueryKey()` and `getListPersonsQueryKey()`).

### Client state

- **zustand only for UI state shared across the two panels that doesn't belong in the URL**:
  `map/store.ts` holds the map's current `bbox` (for "Only in map view") and a pending map pick.
  Don't put server data in zustand.
- Per-device preferences that should follow the user (divider position): `usePreference`.
- Everything else is component state.

### Forms

No form library. Every editor follows the same shape (see `TripFieldsForm`, `StopsEditor`,
`LegsEditor`):

1. `type Values` (strings for inputs), `initial(existing?)` and `toPayload(values)` that builds
   the generated `…In`/`…PatchIn` type (so a schema change is a type error).
2. `validate(values) → Record<field, message>` for what the user can fix before sending
   (required fields, end before start, unknown time zone). Exported and unit-testable.
3. Submit: `event.preventDefault()`, run `validate`, keep the problems in state; if none, call
   the generated mutation with `{ onSuccess: async () => { await invalidate(id); onDone(); } }`.
4. Show errors next to fields: `errors = { ...fieldErrors(mutation.error), ...shown }`. The
   keys are API field names (`title`, `end_date`, `start_utc`), so client and server messages
   land in the same place. A non-field error (403, 409, a plain 422 like "unknown stop") shows
   once via `<MutationError>`; skip it when field errors exist.
5. `<form noValidate aria-label="…">` and `<Field label htmlFor>` for every input: tests and
   e2e find inputs by label, so labels are part of the contract.
6. Times: legs and stops store UTC plus an IANA zone. Use `ZonedTimeInput` (wall-clock
   `datetime-local` + zone with suggestions) and convert with `zonedToUtc` / `utcToZoned`;
   display with `formatInZone`. Dates (trip start/end) are plain `YYYY-MM-DD`; display with
   `formatDate`, never `new Date("2024-05-01")` (that shifts by the browser's zone).
7. Places: `PlaceInput` (pick on the map, airport search, or typed "lat, lon"). There is no
   address search: no forward geocoder (D-20); GeoNames isn't loaded yet.
8. Big records are edited in sections that save on their own (the trip edit page: fields,
   people, stops, legs), not one giant form.

## 4. Errors and permissions

- The server decides; the UI only hides what it knows the user can't do and explains refusals.
  The API's rules (api.md §17): **401** signed out, **403** a visible thing you may not change,
  **404** something you can't see (never "forbidden", so existence isn't revealed), **409**
  duplicate, **422** invalid data or an unusable reference.
- **Loading one thing**: `<QueryState query what="trip">` renders loading, then for 404 "This
  trip doesn't exist or isn't shared with you.", for 403 the server's reason, for 5xx/network a
  message with "Try again". Use it for every by-id page.
- **Hiding controls** uses the flags the API sends, never role checks re-implemented in the
  client: `trip.access.edit / delete / contribute / add_leg`, `leg.can_edit / can_delete`,
  `stop.can_edit`, contribution `can_edit / can_delete`, person `can_edit`. The only role check
  is `me.role !== "viewer"` for create buttons (Viewers are read-only, D-27).
- A page the user can see but not edit (e.g. `/trips/12/edit` for a participant) says "You
  can't edit this trip." with a link back, instead of a broken form.
- Mutation errors render in `<MutationError error what>` (role="alert") near the control.
- Never show emails: other people appear by `display_name` only (D-72); the API never sends
  more.

## 5. Map layers

- `map/MapLayers.tsx` is the one list of everything drawn on the shared map; both shells render
  it inside `BaseMap`. Each layer reads the URL and returns `null` when it doesn't apply
  (`HistoryLayers` on `/history`, `TripLayers` on `/` and `/trips…`, `LegRouteLayer` on a leg's
  route page). Order in the file is drawing order.
- **Data**: GeoJSON sources for small per-user data (trips, a route), vector tiles for big data
  (raw history; trip tiles later). Build GeoJSON in pure functions (`map/geo.ts`), memoized with
  `useMemo`; they are unit-tested without WebGL.
- **Trips layer** (`TripLayers`): `GET /trips/map` with the list's filters (minus "Only in map
  view", which would make the map chase itself) returns visible trips' stops and legs (≤ 2000
  newest trips). Legs are straight lines between their end points (stop places, else airports),
  dashed until routed; flights are great-circle arcs computed in the client. On a trip's pages
  every trip is drawn, the open one highlighted, labelled and fitted (`fitBounds` once per trip).
  Colours by mode come from `trips/labels.ts` (`MODE_COLORS`), shared with legends.
- **Clicks**: one map-level listener per layer group (`map.on("click")` with
  `queryRenderedFeatures` on its own layer ids), as in `HistoryLayers`. A pending map pick takes
  precedence: check `useMapStore.getState().pick` first.
- **Picking a point for a form**: `useMapStore().startPick(label, onPick)`; `MapPickHandler`
  shows the banner, a crosshair, takes the next click, and Esc cancels.
- **Symbol layers** must set `"text-font": ["Noto Sans Regular"]`: the basemap's glyph server
  doesn't have MapLibre's default font (a 404 in the console otherwise).
- **Where routed lines plug in (items 25-26)**:
  - First step (item 25, backend only): in `trip_map` (backend/travel/trips/api.py), a leg with
    a current route returns that route's simplified geometry as `coordinates` with
    `routed: true` (from `route_simplified` at a coarse zoom bucket, or the route itself
    simplified). The frontend needs no change: the line turns solid by itself.
  - Map at scale (T19's trip MVT): add `GET /tiles/trips/{z}/{x}/{y}.mvt` reading
    `route_simplified` under RLS (map-rendering.md §14) and replace the `trip-legs` GeoJSON source
    with a vector source of the same layer id and properties (`trip_id`, `leg_id`, `mode`,
    `routed`); keep the stops source. Clicks and highlighting keep working because they use
    the same property names.
  - The leg's route view `/trips/:tripId/legs/:legId/route` is the editor's slot:
    `routing/LegRoutePage.tsx` (controls, versions; "Propose a route" from item 25) and
    `routing/LegRouteLayer.tsx` (map: today the current version; item 26 adds anchors and the
    live route). Item 26 lazy-loads its editor component there, desktop only. Saving always
    creates a new version (rule 5); nothing re-routes a saved one.

## 6. Shells and platform code

- Both shells render the same routes and map layers; the mobile shell (half map, list below,
  tabs) gets every page for free, editing included. Mobile-specific pages or tabs are T29's
  decision (item 30).
- Platform APIs (keyboard, file pickers, notifications) only through `src/platform/`. Shortcuts:
  `useShortcuts({ e: … }, enabled)`; single keys or "g m" sequences, never Ctrl/Alt/Meta;
  ignored while typing except Esc. Add each to `ShortcutHelp`.
- `window.confirm` is acceptable for destructive actions until a dialog component exists.

## 7. Tests

- **Vitest + Testing Library**, files next to the code (`TripEditPage.test.tsx`). MapLibre is
  mocked (`test/setup.ts`): sources render as `data-testid="source-<id>"` with `data-tiles` or
  `data-features` (GeoJSON feature count), so map layers are testable without WebGL.
- **Pages**: `renderAt(url, routes, me?)` from `test/render.tsx` renders the real routes, map
  layers and auth gate at a URL against `stubFetch` (a route table of `{method, path, status,
  body}`; unmatched requests answer 404). It also renders a `data-testid="location"` probe for
  asserting navigation and filter URLs. Inspect requests with `requests(fetchMock)` ("METHOD
  /path?query") and `lastBody(fetchMock, method, path)`.
- **Fixtures**: `test/trips.ts` (`makeTrip`, `makeDetail`, `makeLeg`, `makeStop`,
  `makeParticipant`, `EMPTY_MAP`), synthetic names only. Override fields per test.
- Find elements by role and label (`getByRole("form", { name: "New stop" })`,
  `getByLabelText("Title")`); wait for async options before selecting them
  (`findByRole("option", …)`).
- What to cover per page: renders the data; empty state; 404/403 text; controls hidden without
  access; the exact request body of each mutation; validation messages; navigation after save.
- Pure modules (`filter.ts`, `geo.ts`, `lib/time.ts`, `errors.ts`) get plain unit tests,
  including time zones with DST gaps and the antimeridian.
- **e2e** (`./dev e2e`): `e2e/smoke.mjs` signs in as dev-member and runs the main flows in a
  real browser; the catalog flow creates a trip, adds the user, two stops (typed coordinates and
  a map click) and a leg, checks the detail page, edits the title and deletes the trip. Use
  `getByLabel(…, { exact: true })` (labels are substring-matched otherwise) and wait for the
  page's heading after navigating.
- Any new endpoint needs backend permission tests per actor (`tests/permissions/`), a matrix
  row if it's a new action, and a regenerated client (`./dev manage export_openapi >
  frontend/src/api/openapi.json && ./dev npm run gen:api`; commit both files). Ninja names
  schemas by class name: a nested `Kind`/`Visibility` enum clashes, so give enums distinct names
  (`StopKind`, `PersonVisibility`).

## 8. Item 21 checklist (the rest of T19, two builder-medium dispatches)

Each dispatch: follow sections 2-7, add tests for every new page and mutation, keep `./dev test`,
`./dev lint` and `./dev e2e` green, update this doc where a pattern grows.

**21a: the list as a working tool.**
- [ ] Keyboard list navigation (§18.4): `j`/`k` move a cursor, `Enter`/`o` open, `x` toggle
      select, `Shift+j/k` extend, `*` then `a`/`n` select all/none, `f` fit the map to the
      selection, `e` edit the cursor's trip. Selection lives in a small zustand store in
      `trips/` (it spans panels; not in the URL). Map highlights selected trips.
- [ ] Bulk bar for a selection (`POST /trips/bulk`, operation `bulkEditTrips`): tag (`t`),
      purpose (`u`, `1`-`7` direct), participants (`p`), visibility. Show the 403 body's
      `refused` list per trip (all or nothing, D-89).
- [ ] Paging past 200 (`offset`, "Load more" or `useInfiniteQuery` with the generated
      `listTrips` function); keep the count line.
- [ ] More filters: person (`person=`, picker from `useListPersons`), status, visibility. The
      header search box and its `/` shortcut (desktop shell) drive the list's `q`.
- [ ] Shortcut help rows; e2e: select two trips and tag them in bulk.

**21b: the trip page complete.**
- [ ] Tags on a trip: `listTripTags`/`addTripTag` (`{tag_id}` or `{name}` creates an own tag)/
      `removeTripTag`, shown with author; a small "My tags" page (`/tags`: rename, colour, delete
      via `updateTag`/`deleteTag`).
- [ ] Per-leg participants (`setLegParticipation`, `setMyLegParticipation`) and public consent
      (`setParticipantConsent`, only where `can_set_consent`).
- [ ] Notes (`listNotes`, `addNote`, `updateNote`, `deleteNote`, honouring `can_edit` /
      `can_delete`); participants who may contribute (`access.add_leg === "contribution"`) can
      add their own legs (the leg form, with `participant_scope` fixed to author).
- [ ] Flight legs: airline search (new `GET /reference/airlines?q=`, read-only reference data,
      same tests as `searchAirports`), `airline_id`, seat, cabin; show airport codes on the
      detail page (add the airport labels to `LegOut` or look them up).
- [ ] People you manage: rename/visibility (new `PATCH /persons/{id}`: managing user or Admin;
      matrix row exists as "Person: edit"; API tests per actor).
- [ ] Purpose management (new `POST/PATCH /purposes`, own purposes; API tests per actor) if
      Adam wants more than the seven defaults.
- [ ] Leg vehicle picker waits for `GET /vehicles` (item 23, T21); leave a TODO in the leg form.

Not in item 21: route proposal and editor (items 25-26), photos (T31), GPS tracks UI (T22),
review queue (item 19), mobile tabs (item 30), public sharing settings (phase 8).

## 9. Decisions (D-90, pending Adam)

Summarised here; full text in [decisions.md](../decisions.md).

1. URL as the single source of page and filter state; zustand only for cross-panel map state.
2. Generated React Query hooks only; invalidate per feature instead of editing the cache.
3. No form library: controlled state, `validate`, server field errors in the same slots.
4. Trip map from a JSON endpoint (`GET /trips/map`) until routes exist; straight legs dashed,
   flights as client-side great-circle arcs.
5. Stops are placed by map click, airport or coordinates (no address search).
6. "Add me" creates the account's own linked person once (`POST /me/person`); new people
   without accounts via `POST /persons` (family-visible by default).
7. The trip editor saves section by section; a new trip is created from its fields first.
8. Public visibility isn't offered in the trip form until sharing settings exist (phase 8).
