# AdventureLog fork-base evaluation (2026-10-19)

Source: read-only clone of https://github.com/seanmorley15/AdventureLog (branches `development`
@647bb89f, `main` @5673ef5 = v0.13.0, `daybasedtrips-abisko` @728450c2), plus `gh api` stats
pulled 2026-10-19. No code from it was executed. Paths are relative to `backend/server/` unless
they start with `frontend/`.

**Bottom line: don't fork; mine for ideas.** Backend stack matches (Django 5.2 + GeoDjango +
PostGIS), but almost none of the required data model exists, the frontend is SvelteKit, and
upstream churn is too high for a model-rewriting fork to keep merging.

## Maintenance (gh api, 2026-10-19)

| Metric | Value |
|---|---|
| Stars / forks | 3,824 / 259 |
| License | GitHub `NOASSERTION`; text is GPL-3.0 with a custom header dropping "or any later version" (effectively GPL-3.0-only) |
| Open issues / PRs | 209 / 26 |
| Closed issues / merged PRs (12 mo) | 171 / 53 |
| Contributors | 47 with logins (54 incl. anonymous) |
| Commits (12 mo) | `main` 183 by 22 authors; `development` 320 by 44 authors (17 Weblate) |
| Top-author share | seanmorley15: 56% (`main`), 45% (`development`), 89% all-time (1651/1857) |
| Last commit | `main` 2026-08-12; `development` 2026-10-19 |
| Releases | v0.13.0 2026-08-12 · v0.12.1 2026-05-25 · v0.12.0 2026-02-23 · v0.11.0 2025-09-01 · v0.10.0 2025-06-09 · v0.9.0 2025-03-19 · v0.8.0 2025-01-08 · v0.7.1 2024-11-13 |

Healthy and active, but a single-maintainer project. Recently added `cloud/` and `billing/` apps
(Stripe, `CLOUD_MODE`): a hosted commercial offering is in progress.

## Requirement fit (0 absent · 1 idea only · 2 partly reusable · 3 fully covered)

| Requirement | Score | Evidence |
|---|---|---|
| Django + GeoDjango + PostGIS | 3 | Django==5.2.13, postgis backend, `PointField(srid=4326)` |
| React + TS + MapLibre | 1 | SvelteKit 2 / Svelte 5 + svelte-maplibre |
| Trips with ordered legs | 1 | `CollectionItineraryItem` (generic FK + date + order); no legs |
| Per-leg frozen routes with versions | 0 | No LineString fields; `Transportation` has origin/destination points only |
| Participants with per-leg overrides | 0 | Only `Collection.shared_with` (users) |
| Contributions with author attribution, edit-own-only | 0–1 | Shared users get full write; their items are re-owned by the collection owner (`serializer.save(user=collection.user)`) |
| PostgreSQL RLS | 0 | None |
| Vehicles with ownership history | 0 | None |
| Home periods | 0 | None |
| Person vs user split | 0 | None |
| Import batches with raw files | 0 | Only a full-account backup ZIP |
| Append-only raw GPS points | 0 | None |
| IANA tz per leg endpoint | 2 | `Transportation.start_timezone`/`end_timezone` CharFields |
| Google Timeline import + diff | 0 | None |
| OwnTracks / Overland ingestion | 0 | None (APIKey auth class is scaffolding) |
| Valhalla routing, drag-to-reshape | 0 | None; straight lines between points |
| Offline reverse geocoding in PostGIS | 1 | Online Nominatim/Google; ISO 3166-2 matched to dr5hn dataset; polygons dropped |
| Flights with OurAirports/OpenFlights | 1 | `Transportation(type='plane', flight_number, start_code, end_code)` free text |
| County/state/country stats | 1 | Counts `VisitedRegion`/`VisitedCity` rows; no counties, no polygon containment |
| Public pages, allowlist, privacy zones | 1 (2 on abisko) | `is_public` flags; abisko adds `story_groups` allowlist + unlisted `share_secret`; no privacy zones |
| OIDC via Authentik | 3 | allauth `openid_connect`, Authentik guide, `FORCE_SOCIALACCOUNT_LOGIN` |
| Immich with proxied thumbnails | 2 | `integrations/views/immich_view.py` proxies `size=preview`; needs hardening |

## Details

- **Models:** `Location` (point, is_public, tags array), `Visit`, `Collection` (shared_with M2M),
  `CollectionInvite`, `Transportation`, `Lodging`, `Note`, `Checklist`, `ContentImage` (generic FK,
  image or immich_id), `ContentAttachment`, `Category`, `Trail`, `Activity` (gpx_file),
  `CollectionItineraryDay/Item`; worldtravel `Country`/`Region`/`City` (points) + visited tables;
  `CustomUser`, `APIKey` (PBKDF2 + prefix); integrations (Immich, Strava, Wanderer, Endurain);
  achievements; billing. Only `PointField`s; GPX kept as files.
- **Sharing:** per collection; `IsOwnerOrSharedWithFullAccess` gives shared users read/write on
  every item; visibility = per-object `is_public` boolean enforced by queryset filtering; no RLS.
- **Features:** backup ZIP import/export, GPX per activity, Strava/Endurain/Wanderer; no Timeline,
  no flight import, no tracking, no routing; MapLibre with GeoJSON (no vector tiles), ~25
  basemaps; stats via background-thread online reverse geocoding; public collections/profiles,
  OG images, PDF export, ICS feed; big itinerary planner; 29 languages.
- **Auth:** django-allauth 0.63.3 (old; current 65.x) headless + mfa (TOTP only, no passkeys);
  DRF APIKey or session auth; SvelteKit server proxies `/api`.
- **Immich:** per-user `ImmichIntegration` with **plaintext** API key, serializer
  `fields='__all__'` returns the key to the client; proxy sets `Cache-Control: public` on private
  images; no SSRF check on `server_url`; `copy_locally` copies thumbnails as WebP.
- **Security:** DEBUG defaults true; `ALLOWED_HOSTS=['*']`; random SECRET_KEY per start if unset
  (breaks API keys); default admin/admin superuser; rate limits off by default; uploads keep EXIF
  (GPS deliberately extracted); attachments checked by extension. Good: X-Accel-Redirect protected
  media, SSRF-guarded remote fetch, PBKDF2 API keys, Trivy in CI.
- **Tests:** backend 189 test functions (`development`), 4 for collection sharing; frontend 0;
  no Python linter.
- **Size:** Python 30k lines (excl. migrations), Svelte 52k, TS/JS 8.7k; 108 migrations.
- **Merge difficulty:** `main`→`development` (~2 months) touched 318 files (+28.3k/−13.9k);
  abisko reworks `Collection` again. Estimated < 10% of future upstream commits would apply to a
  fork that rewrites the models and drops the Svelte frontend.

## Ideas worth borrowing (reimplement, don't copy — GPL-3.0)

- Ordered placements with partial `UniqueConstraint`s; "exactly one parent" `CheckConstraint`.
- Abisko public allowlist (`story_groups` off by default, per-item private override,
  `share_secret`, expiring/revocable guest links, activity audit log).
- X-Accel-Redirect-style protected media; SSRF-safe remote fetch; prefixed hashed API keys
  (pepper separate from SECRET_KEY).
- Immich tiered-access proxy, but `Cache-Control: private`, encrypted key, never returned.
- Photo-pin layer; per-user basemap choice; ICS feed; PDF export; OG share images.
