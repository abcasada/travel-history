# GPSLogger (Android)

GPSLogger (gpslogger.app, F-Droid; v137, checked 2026-10) can post each location to a custom
URL. It has no OwnTracks format of its own, so it is set up with a JSON body that matches one.

GPSLogger has no setup link here: its profile link (`gpslogger://properties/<https address>`)
makes the phone download a settings file from a web address, and that file would contain the
token, so the server would have to hand the token to anyone with the address. The token page
shows the values to copy instead, and a QR code of the token alone (scan it with a QR scanner
and paste it).

## Setup

1. Install GPSLogger from F-Droid.
2. In **Location trackers**, create a token for **GPSLogger**.
3. In GPSLogger: Logging details → **Log to custom URL**, enable it, then:
   - **URL:** the address shown when you created the token (ends in `/api/v1/ingest/owntracks`)
   - **HTTP method:** POST
   - **HTTP headers:** `Content-Type: application/json`
   - **HTTP body:**

     ```
     {"_type":"location","lat":%LAT,"lon":%LON,"tst":%TIMESTAMP,"acc":%ACC,"alt":%ALT,"vel":%SPD_KPH,"batt":%BATT,"tid":"gl"}
     ```

   - **Basic authentication:** user name `travel` (anything works), password the token.
4. Allow location "all the time" and unrestricted battery use (see the
   [overview](README.md#battery)).
5. Check: start logging; the token's "last used" time updates.

## Notes

- Use `%TIMESTAMP` (seconds since 1970), not `%TIME`: GPSLogger URL-encodes the text forms.
- The body must stay valid JSON. If a value is empty (some phones report no altitude), the
  server refuses the request with 400; remove that field from the body.
- GPSLogger keeps unsent points and resends them later; the server drops duplicates.
