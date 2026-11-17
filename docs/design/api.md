# API outline

Moved from PLAN.md §17 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 17. API outline

JSON REST under `/api/v1/`, OpenAPI schema generated; TypeScript types generated from it.
Session cookie + CSRF for the PWA; OIDC bearer tokens for the companion; device tokens only for
ingestion.

| Area | Endpoints |
|---|---|
| Auth (public) | `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, `GET /auth/reauth?next=` (forces `prompt=login`) |
| Me | `GET /me`, `POST /me/privacy-ack`, `GET/PUT /preferences/{key}?device_class=` |
| Trips | `GET/POST /trips` (filters: date range, purpose, tag, person, vehicle, mode, status, visibility, bbox, text), `GET/PATCH/DELETE /trips/{id}`, `POST /trips/bulk` (tag, purpose, visibility, participants for many), `GET /trips/duplicates?start=&end=`, `POST /trips/{id}/join`, `POST /trips/merge`. Built in item 6: list (filters `from`, `to`, `visibility`, `status`, `person`, `q`; `limit`/`offset`, newest first), create, detail (with legs, participants, the caller's `access`, and `sharing` for core editors), patch, delete. Item 13: list filters `purpose`, `tag`, `vehicle`, `mode` (repeat a parameter for any-of; different filters all apply) and `bbox=minLon,minLat,maxLon,maxLat` (a leg's current route, a leg's airports or a stop's place inside; minLon > maxLon crosses the antimeridian); every trip summary carries its `tags` (owner's first, each with its author); the detail adds `stops`. `POST /trips/bulk` (`trip_ids` ≤ 500; `purpose_id`, `visibility`, `add_/remove_person_ids`, `add_/remove_tag_ids`): all or nothing, 403 `{detail, refused: [{trip_id, reason}]}`. Duplicates, join and merge: left to the merge tool (T35, D-89). |
| Legs and routes | `GET/POST /trips/{id}/legs`, `PATCH/DELETE /legs/{id}`, `GET /legs/{id}/routes` (versions), `POST /legs/{id}/routes` (new frozen version), `PUT /legs/{id}/my-participation`. Built in item 6: `GET/POST /trips/{id}/legs`, `GET/PATCH/DELETE /legs/{id}`, `PUT /legs/{id}/my-participation` and `PUT /legs/{id}/participants/{person_id}` (body `{on_leg}`; stored as the difference from the leg's base set). Item 13: `POST /trips/{id}/legs/order` (`{leg_ids}`: every leg, in order; core editors; contributed legs included), `GET /legs/{id}/routes` (versions newest first, no geometry, `is_current`), `GET /routes/{id}` (one version with GeoJSON `geometry` and `waypoints`). Routes have no write endpoint yet; new versions come with the editor (T25). Legs carry `can_delete` (Q-16). |
| Participants and contributions | `GET/POST/DELETE /trips/{id}/participants`, `PUT /trips/{id}/participants/{pid}/consent`, `GET/POST /trips/{id}/notes`, `PATCH/DELETE /notes/{id}`, `GET/POST /trips/{id}/media`, `PATCH/DELETE /media/{id}`, `GET/POST/DELETE /trips/{id}/tags`, `POST /trips/{id}/tracks`. Built in item 6: `GET/POST /trips/{id}/participants`, `DELETE /trips/{id}/participants/{person_id}`, `PUT /trips/{id}/participants/{person_id}/consent` (`pid` is the person id). Item 13: `GET/POST /trips/{id}/notes`, `PATCH/DELETE /notes/{id}`; `GET/POST /trips/{id}/tracks` (`{start_utc, end_utc, public_consent}`: a time range of the caller's own points, ≤ 366 days), `PATCH/DELETE /tracks/{id}`; `GET /trips/{id}/media`, `PATCH/DELETE /media/{id}` (metadata only: caption, leg, stop, consent; uploads in T31); `GET/POST /trips/{id}/tags` (`{tag_id}` or `{name}`, own tags; returns the trip's tags), `DELETE /trips/{id}/tags/{tag_id}`; `GET/POST /trips/{id}/stops` (`place_id` or a new `place {name, address, lon, lat}`), `PATCH/DELETE /stops/{id}`. Every contribution says `can_edit` and `can_delete`. Own definitions: `GET/POST /tags`, `PATCH/DELETE /tags/{id}`, `GET /purposes`. |
| Review queue | `GET /review/candidates`, `POST /review/candidates/{id}/accept\|reject\|split`, `POST /review/merge`, `GET /review/flags`, `POST /review/flags/{id}/resolve` |
| People, vehicles | `GET/POST /persons`, `PATCH /persons/{id}`; `GET/POST /vehicles`, `GET /vehicles/match?year=&make=&model=&nickname=&plate_last4=`, `PATCH /vehicles/{id}`, `GET/POST /vehicles/{id}/ownership`, `POST /vehicles/merge`, `POST /vehicles/quick-rental` |
| Home periods | `GET/POST /home-periods`, `PATCH/DELETE /home-periods/{id}`, `GET /home-periods/suggestions`, `GET /home-periods/validation` |
| Uploads and imports | `POST /uploads` (→ id, chunk size), `PUT /uploads/{id}/chunks/{n}` (+ `Content-Range`, SHA-256 per chunk), `POST /uploads/{id}/complete` (→ import batch), `GET /imports`, `GET /imports/{id}` (summary) |
| Flights | `GET /flights/records?status=&import_batch=` (own imported flight records with problems/warnings), `GET /reference/datasets` (attribution page) |
| Raw history | `GET /history/tiles/{z}/{x}/{y}.mvt?from=&to=&source=` (points), `GET /history/segments/tiles/{z}/{x}/{y}.mvt?from=&to=` (Timeline segments, z ≥ 5), `GET /history/coverage?from=&to=&tz=` (days with data, ≤ 400 days), `GET /history/bakeoff`. Built in milestone 2.3 except the bakeoff; segments are served as tiles rather than a JSON list (bounded per tile; §14). |
| Flights | `GET /flights/template.csv`, `POST /flights/import` (upload id), `GET /flights/unmatched` |
| Routing | `POST /routing/route` (waypoints → OSRM-format route + provenance), `POST /routing/match` (internal use) |
| Stats | `GET /stats/summary`, `/stats/territories?level=country\|region\|county&mode=through\|stopped`, `/stats/distance?by=vehicle\|mode\|year`, `/stats/flights` |
| Tiles | `GET /tiles/trips/{z}/{x}/{y}.mvt` |
| Devices (tracking) | Built in item 7 as `GET/POST /tracking/tokens` (list own; create → the token, once, with its setup link and QR codes) and `POST /tracking/tokens/{id}/revoke`. No separate setup endpoint: setup needs the token, which exists only in the create response. |
| Ingestion (public, token) | `POST /ingest/owntracks` → `[]`, `POST /ingest/overland` → `{"result":"ok"}`. Plain Django views, not in the OpenAPI schema; statuses 400/401/405/411/413/415/429 ([tracking.md](tracking.md) §9.1). |
| Push | `POST/DELETE /push/subscriptions` |
| Admin | `GET /admin/access-requests`, `POST /admin/access-requests/{id}/approve\|reject` (requires recent re-auth), `GET/POST/DELETE /admin/allowlist`, `GET/POST /admin/invites`, `GET/PATCH /admin/users`, `GET/POST /admin/transfers` |
| Export | `POST /export` (job) → `GET /export/{id}` (zip: GeoJSON, GPX, CSV, original files) |
| Public (separate URLconf, `travel_public` role) | `GET /` (landing), `GET/POST /request-access`, `GET /invite/{token}`, `GET /t/{slug}` (unlisted trip), `GET /u/{profile}`, `GET /u/{profile}/{slug}`, `GET /pm/{id}/{size}` (public media) |

Trips API status codes and rules (work-order item 6): 401 signed out or deactivated; 404 for a
trip, leg or person the caller can't see; 403 for a visible trip the caller may not change;
409 for a duplicate participant or tag (and for moving a GPS track that already has a route); 422 for invalid data and for references the caller can't use
(another user's purpose, a hidden vehicle). Details in [permissions.md](permissions.md) §6.3.
