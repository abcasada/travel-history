# Photos and Immich

Moved from PLAN.md §16 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 16. Photos and Immich

### 16.1 Basic photos (phase 7)

- One cover image per trip plus up to `photo_limit_per_contributor` photos (default 10,
  configurable per trip) per contributor. The owner and participants (as contributions) add them.
- On upload, the worker decodes the image (Pillow, with pillow-heif for HEIC), applies the EXIF
  orientation, reads the capture time (EXIF `DateTimeOriginal` + `OffsetTimeOriginal`, else trip
  time zone), and writes two **new** files with no metadata at all: a display copy (longest edge
  2048 px, WebP/JPEG q≈82) and a thumbnail (400 px). Originals are discarded after processing.
- Files live on the HDD: `/bulk/media/<trip>/<media id>-display.webp`, `-thumb.webp`.
  Served through Django with permission checks (`Cache-Control: private`), never from a public
  static path. Public pages serve the same stripped copies via the public renderer.
- No map placement or location features for basic photos (they have no location).
- Tests: a synthetic JPEG with GPS, camera serial and comment tags in EXIF/XMP/IPTC comes out
  with none of them; the capture time is preserved in the DB.

### 16.2 Immich (phase 10 — designed now, not built)

- **Per-user connection:** each user stores their own Immich base URL + API key
  (`integration_setting`, key encrypted with Fernet; never returned to the client; base URL
  validated against SSRF rules — LAN Immich is allowed explicitly by config, since Immich will run
  on this server).
- **Links, not copies:** `media.source = immich`, `media.external_id = <asset id>`; trips, legs and
  stops link to Immich asset ids. Originals never enter this app.
- **Suggestions:** for a trip, query the owner's Immich for assets taken inside the trip window
  (metadata search with taken-after/taken-before); the user confirms which to link.
- **Viewing:** the backend proxies thumbnails/previews using the **photo owner's** credentials and
  enforces the trip's visibility, so viewers need no Immich account. Responses are
  `Cache-Control: private`.
- **Public pages:** for public trips the snapshot builder fetches the chosen previews once,
  re-encodes them without metadata (location stripped) and stores the stripped derivative like a
  basic photo; public pages never proxy live to Immich.
- **Swap:** any trip image, including the cover, can be swapped between a basic photo and an
  Immich asset (same `media` row, different `source`).
- **Optional later:** write GPS from location history back to Immich assets lacking it (asset
  update with latitude/longitude), only for the user's own assets, with preview and confirmation.
