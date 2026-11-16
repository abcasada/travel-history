# Colota (Android, recommended)

Colota (colota.app; v1.20, checked 2026-10; Play, F-Droid, IzzyOnDroid) is an actively
maintained Android tracker with an offline queue, tracking profiles and setup by link or QR
code. This server sets it up with its **OwnTracks** request format, whose fields are documented
and checked strictly here.

## Setup

1. Install Colota.
2. In **Location trackers**, create a token for **Colota**.
3. Set Colota up with the link or QR code:
   - **On the phone itself:** open this page on the phone and tap **Open in Colota**.
   - **From a computer:** scan the setup QR code (Colota's own scanner, or the camera app).

   Colota shows a confirmation screen with every setting it will apply (the token is masked).
   Check that the host under "Sends locations to" is your server, then tap
   **Apply Configuration**. The link sets: endpoint (`…/api/v1/ingest/owntracks`), request
   format OwnTracks, method POST, and Bearer authentication with the token.
4. Allow location "all the time" and unrestricted battery use (see the
   [overview](README.md#battery)).
5. Check: the token's "last used" time updates after Colota's next sync.

## Manual setup

Settings → Connection: **Request format** OwnTracks; **Endpoint** the address shown when you
created the token; **Authentication** Bearer with the token.

Colota's **Overland** format (batches of up to 500 points) also works with the same token at
`…/api/v1/ingest/overland`, but its exact fields aren't documented; if the server refuses it
(400 with a field name in the log), use the OwnTracks format.

## Notes

- Colota's own "share configuration" feature leaves credentials out by default; if you include
  them, the link carries the token in plain text, so treat it like the token.
- Tracking profiles (e.g. more often while charging or in the car) are set in Colota and don't
  affect the server.
