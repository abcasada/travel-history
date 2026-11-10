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
| Trips | `GET/POST /trips` (filters: date range, purpose, tag, person, vehicle, mode, status, visibility, bbox, text), `GET/PATCH/DELETE /trips/{id}`, `POST /trips/bulk` (tag, purpose, visibility, participants for many), `GET /trips/duplicates?start=&end=`, `POST /trips/{id}/join`, `POST /trips/merge` |
| Legs and routes | `GET/POST /trips/{id}/legs`, `PATCH/DELETE /legs/{id}`, `GET /legs/{id}/routes` (versions), `POST /legs/{id}/routes` (new frozen version), `PUT /legs/{id}/my-participation` |
| Participants and contributions | `GET/POST/DELETE /trips/{id}/participants`, `PUT /trips/{id}/participants/{pid}/consent`, `GET/POST /trips/{id}/notes`, `PATCH/DELETE /notes/{id}`, `GET/POST /trips/{id}/media`, `PATCH/DELETE /media/{id}`, `GET/POST/DELETE /trips/{id}/tags`, `POST /trips/{id}/tracks` |
| Review queue | `GET /review/candidates`, `POST /review/candidates/{id}/accept\|reject\|split`, `POST /review/merge`, `GET /review/flags`, `POST /review/flags/{id}/resolve` |
| People, vehicles | `GET/POST /persons`, `PATCH /persons/{id}`; `GET/POST /vehicles`, `GET /vehicles/match?year=&make=&model=&nickname=&plate_last4=`, `PATCH /vehicles/{id}`, `GET/POST /vehicles/{id}/ownership`, `POST /vehicles/merge`, `POST /vehicles/quick-rental` |
| Home periods | `GET/POST /home-periods`, `PATCH/DELETE /home-periods/{id}`, `GET /home-periods/suggestions`, `GET /home-periods/validation` |
| Uploads and imports | `POST /uploads` (→ id, chunk size), `PUT /uploads/{id}/chunks/{n}` (+ `Content-Range`, SHA-256 per chunk), `POST /uploads/{id}/complete` (→ import batch), `GET /imports`, `GET /imports/{id}` (summary) |
| Raw history | `GET /history/tiles/{z}/{x}/{y}.mvt`, `GET /history/segments?from=&to=`, `GET /history/coverage?from=&to=`, `GET /history/bakeoff` |
| Flights | `GET /flights/template.csv`, `POST /flights/import` (upload id), `GET /flights/unmatched` |
| Routing | `POST /routing/route` (waypoints → OSRM-format route + provenance), `POST /routing/match` (internal use) |
| Stats | `GET /stats/summary`, `/stats/territories?level=country\|region\|county&mode=through\|stopped`, `/stats/distance?by=vehicle\|mode\|year`, `/stats/flights` |
| Tiles | `GET /tiles/trips/{z}/{x}/{y}.mvt` |
| Devices (tracking) | `GET/POST /devices`, `DELETE /devices/{id}` (revoke), `GET /devices/{id}/setup` (QR/deep link) |
| Ingestion (public, token) | `POST /ingest/owntracks`, `POST /ingest/overland` |
| Push | `POST/DELETE /push/subscriptions` |
| Admin | `GET /admin/access-requests`, `POST /admin/access-requests/{id}/approve\|reject` (requires recent re-auth), `GET/POST/DELETE /admin/allowlist`, `GET/POST /admin/invites`, `GET/PATCH /admin/users`, `GET/POST /admin/transfers` |
| Export | `POST /export` (job) → `GET /export/{id}` (zip: GeoJSON, GPX, CSV, original files) |
| Public (separate URLconf, `travel_public` role) | `GET /` (landing), `GET/POST /request-access`, `GET /invite/{token}`, `GET /t/{slug}` (unlisted trip), `GET /u/{profile}`, `GET /u/{profile}/{slug}`, `GET /pm/{id}/{size}` (public media) |
