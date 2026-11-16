# OwnTracks (Android and iPhone)

OwnTracks (owntracks.org; Android 2.5, iOS 27, checked 2026-10) sends one message per location
over HTTPS, with the token as the HTTP password.

## Setup

1. Install OwnTracks from the app store (Android: also on F-Droid).
2. In **Location trackers**, create a token for **OwnTracks**.
3. Set the app up with the link or QR code:
   - **On the phone itself:** open this page on the phone and tap **Open in OwnTracks**.
   - **From a computer:** scan the setup QR code with the phone's camera (iPhone), or with a QR
     scanner and open the link it shows (Android).

   This sets: mode HTTP, the server address, authentication on with user name `travel` and the
   token as password, a device id and two-letter tracker id from the token's name, and
   *significant changes* monitoring.
4. Allow location **Always** / **all the time** and unrestricted battery use (see the
   [overview](README.md#battery)).
5. Check: in OwnTracks, publish your location once (the upload icon). The token's "last used"
   time on the **Location trackers** page updates.

## Manual setup

Preferences → Connection: **Mode** HTTP; **URL** the address shown when you created the token
(it ends in `/api/v1/ingest/owntracks`); **Authentication** on, user name anything (e.g.
`travel`), password the token. Leave **encryption** off: encrypted payloads are refused.

## Monitoring modes

- **Significant** (default here): roughly every 500 m or 5 minutes when moving; light on the
  battery. Good for the Timeline replacement.
- **Move**: frequent points (e.g. every 100 m); good on road trips, heavy on the battery.

Switch modes from the app's main screen.
