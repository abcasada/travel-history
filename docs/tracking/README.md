# Location tracking: setup guides

Your phone can send its location to your raw history here, as a self-hosted replacement for
Google Timeline (PLAN.md §9). Only you can see your raw history; not even the Admin can.

| Phone | Recommended app | Guide |
|---|---|---|
| Android | **Colota** (F-Droid or Play; very active) | [colota.md](colota.md) |
| Android | OwnTracks | [owntracks.md](owntracks.md) |
| Android | GPSLogger (F-Droid) | [gpslogger.md](gpslogger.md) |
| iPhone | **OwnTracks** (light on the battery) | [owntracks.md](owntracks.md) |
| iPhone | Overland (detailed tracks) | [overland.md](overland.md) |

## Getting a token

1. In the app, open the account menu (your name, top right) and choose **Location trackers**.
2. Give the tracker a name (e.g. "My phone"), pick the app, and choose **Create token**.
3. The page now shows a setup QR code and link, the server address, and the token.
   **This is the only time the token is shown.** Set the app up straight away. If you lose the
   token, revoke it and create a new one.
4. When you're done, choose **Done, hide the token**.

One token per app per phone. A token can only add points to your own history: it can't read
anything, and other people's tokens can't write to yours.

## Revoking

**Location trackers** → **Revoke** next to the token. The app gets "unauthorized" from then
on and its points stop arriving at once. Revoking can't be undone; points it already sent stay
in your history. Revoke a token when you replace a phone, uninstall the app, or think someone
saw the token or the QR code.

## What is stored

Time, position, accuracy, altitude, speed, heading and battery level. Everything else the apps
send (Wi-Fi network names, regions, motion, trip details) is checked and thrown away. Points are
never dropped for looking odd: a point that implies an impossible speed (over 400 m/s, faster
than any airliner) is kept with a flag, so the map and trip detection can skip it. Points dated
before 2000 or more than a day in the future are refused and counted in the server log.

## Battery

Trackers only work if the phone lets them run in the background:

- **Android:** location permission "Allow all the time"; battery usage **Unrestricted** for the
  app. Samsung: add the app to "Never sleeping apps" and check again after system updates.
  Xiaomi: enable Autostart and "No restrictions". See dontkillmyapp.com for other makers.
- **iPhone:** location permission **Always**. Don't swipe the app away in the app switcher:
  iOS stops tracking for force-quit apps.

## Troubleshooting

| What you see | Why, and what to do |
|---|---|
| 401 / "unauthorized" | The token is wrong, revoked, or meant for another app (an OwnTracks token doesn't work in Overland). Create a new one for the right app. |
| 429 / "too many requests" | More than 120 requests a minute from one token (or 600 from one network). The app retries later by itself; if it happens often, send less often or use batches (Overland, Colota). |
| 400 with a field name | The app sent a field or value this server doesn't accept (for example after an app update added a field). The app keeps the points and retries; tell the server's operator, who will see the field name in the log. |
| 413 | The request was larger than 5 MB or had more than 1,000 points. Lower the app's batch size. |
| 415 / 411 | The app didn't send JSON with a length (GPSLogger: check the Content-Type header). |

## For the operator

- Endpoints: `POST /api/v1/ingest/owntracks` (answers `[]`) and `POST /api/v1/ingest/overland`
  (answers `{"result":"ok"}`). Neither answer ever contains data. Rules and limits:
  [PLAN.md §9.1](../design/tracking.md).
- Tokens are stored as SHA-256 only; logs never contain them (query-string tokens are removed
  before anything logs the request, and every log line is redacted). Prefer apps that send the
  token in a header: a token in the URL is visible to any proxy in between.
- Settings (`.env`): `TRACKER_BASE_URL` (the address phones use; empty = the address the
  browser used when the token was created), `TRACKER_RATE_PER_TOKEN`, `TRACKER_RATE_PER_IP`.
  Behind a proxy, set `RATELIMIT_CLIENT_IP_HEADER`, or every phone shares one per-address limit.
