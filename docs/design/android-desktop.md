# Android companion and desktop wrapper

Moved from PLAN.md §19 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 19. Android companion and desktop wrapper

### 19.1 Android companion (phase 9)

Kotlin, single-activity, two jobs only:

1. **Background uploads** of Timeline exports and basic trip photos that survive closing the app.
2. **Share target** ("Share to Travel") for `application/json` Timeline files and images, with a
   trip picker (recent and in-progress trips from `GET /api/v1/trips?recent=1`).

Not a tracker (live tracking stays with OwnTracks, GPSLogger, Overland, Colota) and not a second
UI (a button opens the PWA).

- **Login:** OIDC authorization code + PKCE (S256) against the Authentik public client, using
  AppAuth-Android (de facto standard; last release 0.11.1 in 2021 but still maintained enough —
  see §26; fallback: a small Custom Tabs flow). Redirect `com.adamcasada.travel:/oauth2redirect`.
  Tokens in EncryptedSharedPreferences/Keystore; refresh via `offline_access`.
- **Uploads:** the same resumable chunked upload API as the web (§17): `POST /uploads` →
  `PUT /uploads/{id}/chunks/{n}` (32 MB chunks, each with SHA-256; well under Cloudflare's
  100 MB request limit) → `POST /uploads/{id}/complete`. The server offset is persisted, so
  retries resume.
  - API 34+: **user-initiated data transfer (UIDT) job** scheduled when the user taps Upload or
    shares a file (no fixed runtime limit, retried by the system).
  - API 26–33: WorkManager expedited work with `setForeground` (dataSync foreground service).
- **Photos:** uploaded as-is; the server strips metadata (keeps capture time). No media-location
  permission is requested.
- **Distribution:** a signed APK for sideloading, built in a container (Android SDK command-line
  tools image). Signing key kept out of git. Publishing to any store needs Adam's approval.

### 19.2 Desktop wrapper (later)

The PWA is installable now. The frontend isolates three things behind adapters in
`frontend/src/platform/`:

| Adapter | PWA implementation now | Wrapper implementation later |
|---|---|---|
| `files` | `<input type=file>` / File System Access API where available; drag-and-drop | native dialogs, **folder watching** of the Downloads/Timeline folder for auto-import |
| `shortcuts` | in-page key handling (§18.4) | global shortcuts, full key control |
| `notifications` | Web Push + `Notification` API | native notifications |

A thin Tauri 2 wrapper (smaller, Rust) is the likely choice over Electron (§24 D-26); it only
loads the hosted app and implements the three adapters.
