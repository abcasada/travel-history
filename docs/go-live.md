# Go-live runbook

Work-order item 40d (the go-live slice of T38), decision D-105. This is for Adam: the steps that
make the whole app reachable at `https://travel.adamcasada.com`, behind Authentik with a second
factor. Item 40e carries them out after your "go". Nothing in this file has been done yet. The
tunnel, DNS and Authentik changes are yours, in their dashboards. Item 40 adds the email
(SMTP), Turnstile, request-access and public-page parts later.

## Before you start

All of these must be true:

- [ ] Item 41a's security review found no blockers (or item 42a fixed them), and you said "go".
- [ ] Authentik with a forced second factor is live at `auth.adamcasada.com`, and the checks
      below pass.
- [ ] You have signed in to production over the SSH port-forward
      ([production guide](production.md#signing-in-before-go-live-g-4)), and item 40c-3 moved
      your Authentik identity onto the copied account: you see your history and trips, and you
      are Admin.
- [ ] Production is healthy: `./dev prod smoke` passes on the server.
- [ ] The rehearsal passes: `./dev golive-smoke local` builds the deployed commit's image, runs
      it with exactly the go-live settings (scope `all`) against a throwaway database on
      127.0.0.1, and checks everything the outside test below checks. Run it from a checkout of
      the deployed commit. It never touches production.
- [ ] Recommended: `AGE_RECIPIENT` is set in `.env.prod`, so production has an encrypted
      backup (`./dev prod backup-now`).

The order below keeps every step safe on its own. While the scope is still `tracker`, pointing
the tunnel at production shows nothing but the two tracker endpoints. The scope flip is the
moment the app appears, and flipping it back is the fastest way out.

## 1. Authentik checks

In the Authentik admin interface, check the "Travel History" application and its provider
([auth.md §7.2](design/auth.md) items 1, 2 and 5):

1. **Group binding.** Application → **Policy / Group / User Bindings**: exactly one binding,
   the group `travel-users`. Without it, every Authentik user could sign in. (The app also
   refuses an ID token without `travel-users` in `groups`, D-103, but the binding is the first
   wall.)
2. **Strict redirect URIs.** Provider → **Redirect URIs**, both *strict*:
   - redirect: `https://travel.adamcasada.com/auth/callback`
   - post-logout: `https://travel.adamcasada.com/`

   G-4's temporary `http://localhost:8784/auth/callback` and `http://localhost:8784/` stay
   until step 5 below, then go.
3. **Confidential client, claims in the ID token.** Client type *confidential*, *Include claims
   in id_token* on, issuer mode *per provider*, signing key RS256.
4. **Second factor required.** In the authentication flow the provider uses, an
   **Authenticator Validation** stage with device classes WebAuthn and TOTP and
   *Not configured action* = **Force the user to configure an authenticator**. The app also
   refuses a sign-in whose ID token says a password alone was used (`amr: ["pwd"]`, G-5).
   In the same flow, the **User Login** stage's **Session duration**: `weeks=2` (the default
   `seconds=0` ends Authentik's session when the browser closes). The app sends every session
   back through Authentik once an hour to check the account is still in `travel-users`
   (D-108); with a live Authentik session nobody notices, without one everybody signs in again
   with their second factor every hour.
5. **A refusal test** (2 minutes): sign in at `https://travel.adamcasada.com` after step 4 with
   an Authentik user who is *not* in `travel-users` (a throwaway one). Authentik should refuse
   it; if it lets it through, the app answers "not in the group". Delete that user afterwards.

## 2. Tunnel routes

**Zero Trust → Networks → Tunnels**, the main tunnel every `*.adamcasada.com` site uses
(`~/infra/TUNNELS.md`), **Published application routes**.

### travel.adamcasada.com: edit the existing route

Item 8 made this route for the tracker endpoints only. Edit it, don't add a second one:

| Field | Before (tracker only) | After |
|---|---|---|
| Subdomain / Domain | `travel` / `adamcasada.com` | unchanged |
| Path | `^/api/v1/ingest/(owntracks\|overland)/?$` | **empty** (every path) |
| Service type | `HTTP` | `HTTP` |
| URL | `localhost:8783` | **`localhost:8784`** |

Type the old Path without the backslash, which is only Markdown escaping.

**Additional application settings → HTTP Settings:**

- **Disable Chunked Encoding: ON** (keep it on). The tracker endpoints refuse chunked bodies
  with 411, and the go-live smoke checks that locally.
- **HTTP Host Header:** empty. The app recognises its names by the original Host header.
- Everything else at its default. No Cloudflare Access on this route: Authentik is the login,
  and the phone tracker apps couldn't pass Access.

**What happens to the ingest path rule (D-105): it goes.** Production's `web` serves the two
tracker endpoints itself, with the same code, token checks, size caps and rate limits as the
`ingest` service, so one route for the whole host is enough. The `ingest` service stays stopped
(`./dev prod tracker stop` if it's running), which also frees its 512 MB. Phone setup links and
QR codes keep `https://travel.adamcasada.com`, so phones need no change. If tracking ever needs
its own service again, add a separate route with the path rule to `localhost:8783` and drag it
**above** the travel.* route: the tunnel uses the first route that matches.

### trips.adamcasada.com: add or edit its route

Same values as travel.*: Path empty, `HTTP`, URL `localhost:8784`, Disable Chunked Encoding ON,
HTTP Host Header empty. The app answers every request on trips.* with a permanent redirect
(301) to the same path on `https://travel.adamcasada.com`, except the tracker endpoints, which
it serves directly. If trips.* already has a tracker-only route to 8783 from 2026-11-19, edit it
the same way as travel.*.

### Bookkeeping

In `~/infra/TUNNELS.md`, the travel-history row becomes:
`8784 (production web) | travel-history | ~/apps/travel-history-prod | travel.adamcasada.com, trips.adamcasada.com (redirects) | live <date>`.
You make this edit, or approve it.

Not changed: the firewall, the router, other sites and apps, zone-wide Cloudflare settings.

## 3. DNS records

Saving a route normally creates its record. Under **DNS → Records** there should be exactly
these two for the app, and no A or AAAA records for either name:

| Type | Name | Target | Proxy status | TTL |
|---|---|---|---|---|
| `CNAME` | `travel` | `<main tunnel UUID>.cfargotunnel.com` | Proxied (orange cloud) | Auto |
| `CNAME` | `trips` | `<main tunnel UUID>.cfargotunnel.com` | Proxied (orange cloud) | Auto |

`travel` exists since item 8. The UUID is on the tunnel's overview page (its prefix is in
`~/infra/TUNNELS.md`). If saving says a record already exists, delete that record and save the
route again.

**Check, still before the flip:** `./dev golive-smoke https://travel.adamcasada.com --scope tracker`
from the server. Every path but the tracker endpoints answers 404 (now the app's own 404s, with
its headers), the tracker endpoints refuse a bogus token, and trips.* redirects.

## 4. The scope flip

On the server, in `~/apps/travel-history-prod/.env.prod`:

```
TRAVEL_PUBLIC_SCOPE=all
```

then `./dev prod up` (recreates `web` and `worker` with the deployed image; HSTS, the TLS-proxy
setting and `CF-Connecting-IP` are already forced by `compose.prod.yaml`, and the settings
refuse to start without them) and `./dev prod smoke`.

The app is now public, behind the login wall: anonymous visitors see the landing page with a
"Sign in" link and nothing else.

## 5. Outside checks

1. **The go-live smoke, through Cloudflare:** `./dev golive-smoke https://travel.adamcasada.com`
   on the server (or anywhere with the repository). Paste a throwaway tracker token at the
   prompt, or press Enter to skip the token checks. Expect `PASS`. It checks: the landing page
   and every response's headers (HSTS, CSP, nosniff, X-Frame-Options, Referrer-Policy, COOP),
   the installed app's own `index.html` and `sw.js` included; plain HTTP redirected;
   `/auth/login` sending you to Authentik with state, nonce, PKCE and the canonical callback,
   and a Secure, HttpOnly session cookie; every API operation and private page refusing
   anonymous requests, no API docs or schema even with a Bearer header, and a large anonymous
   form post refused (413); the app's own 404s without a debug page and Cloudflare's managed
   robots.txt; the trips.* redirect, which is not an open one; the tracker endpoints unchanged
   on both names; no token in production's logs.
2. **Sign in from outside:** on your phone with Wi-Fi off, open `https://trips.adamcasada.com`.
   It lands on `https://travel.adamcasada.com`; sign in with your second factor and check your
   trips and history.
3. **Remove G-4's temporary URIs** in Authentik (provider → Redirect URIs): delete
   `http://localhost:8784/auth/callback` and `http://localhost:8784/`. Sign out and in again at
   the public address to confirm.
4. If you made a throwaway tracker token, revoke it on **Location trackers**.

## Adding a family member

Do this once per person, after go-live:

1. **Authentik:** create the user (name, email; or send an invitation, §7.2 item 4) and add
   them to the group **`travel-users`**. Nothing else: not `travel-admins`, no other app's group
   unless you mean it.
2. **First sign-in:** they open `https://travel.adamcasada.com` and choose **Sign in**. Authentik
   makes them set up a second factor (a passkey, or an authenticator app) before letting them
   in. The app creates their account as a **Member** (never Admin; only
   `./dev prod manage set_role` changes that).
3. **Link them to their person.** The trips you typed in list them as a person, and trips
   default to `participants` visibility, so they see nothing until their account is linked to
   that person. On the server:
   - `./dev prod manage link_person` lists the accounts and the persons without an account;
   - `./dev prod manage link_person ACCOUNT PERSON` shows what would change (dry run);
   - the same with `--execute` links them (one transaction, written to the audit log).
4. They reload the app and see the trips they were on.

The command refuses a person that already has an account and an account that already has a
person ([auth.md §7.8](design/auth.md)).

## Removing someone's access

1. **Authentik:** remove them from `travel-users` (or deactivate the Authentik user). Every new
   sign-in is refused, and their open sessions end by themselves within the hour: the app sends
   each session back through Authentik once it is an hour old (D-108).
2. **Server, to end it now:** `./dev prod manage deactivate_account` lists the accounts with
   their sessions; `./dev prod manage deactivate_account ACCOUNT` shows what changes (dry run);
   the same with `--execute` deactivates the account and deletes its sessions. Their trips and
   history stay; they read nothing, their tracker tokens stop working, and anything shared with
   them stays shared with their person. `--reactivate --execute` lets them in again.

**A lost or stolen phone** (someone who keeps their access): in Authentik, end their sessions
(the user's **Sessions** tab), then `./dev prod manage deactivate_account ACCOUNT --sign-out
--execute` ends the app's sessions on every device at once. They sign in again on their other
devices. If the phone ran a tracker, revoke its token on **Location trackers**. For your own
phone, the same works: `deactivate_account` refuses to deactivate the only Admin, `--sign-out`
doesn't.

## Rollback

Any one of these is enough; fastest first.

1. **Server, seconds: set the scope back.** In `.env.prod`, `TRAVEL_PUBLIC_SCOPE=tracker`, then
   `./dev prod up`. Both names go back to answering 404 for everything but the tracker endpoints,
   whatever the tunnel says.
2. **Server: stop the app.** `./dev prod down` stops the whole stack (the tunnel then answers
   502). The database volume stays.
3. **Dashboard: delete the routes.** Delete the trips.* route and either delete the travel.*
   route or put it back to the tracker-only values (the "Before" column above). Delete the
   `trips` CNAME if it remains.

After a rollback, sessions made while public stay valid until their hourly check with Authentik
or until the user signs out; that is harmless while the app isn't reachable
(`deactivate_account ACCOUNT --sign-out --execute` ends one account's sessions at once). Nothing
else needs undoing.

## What Cloudflare can see

TLS ends at Cloudflare's edge; from there the request travels through the tunnel to
`cloudflared` on the server and over plain HTTP on localhost to the app. So **Cloudflare can see,
in clear text and in transit, everything you and the family send and receive**:

- every page and API response: trips, stops, legs, people, notes, the history map's tiles and
  points, routes;
- every upload, including a Google Timeline export with your whole location history, and the
  trip spreadsheet;
- session cookies (while valid, they are as good as being signed in), the CSRF token, tracker
  device tokens and the phones' location posts;
- visitors' IP addresses, user agents and request times.

It does not see the database, the backups (encrypted with your age key before they leave the
server), Immich, or anything sent over the LAN, the SSH port-forward or the VPN. Authentik at
`auth.adamcasada.com` goes through the same tunnel, so the same applies to sign-in pages.

This is the same trust you already place in Cloudflare for the other sites. Nothing is meant to
be stored there: by default Cloudflare caches only static files by extension (scripts, styles,
images: the app's code and icons, no data), and the tracker endpoints send
`Cache-Control: no-store`. Don't add a "cache everything" rule for these names. Cloudflare's **managed robots.txt** answers
`/robots.txt` at the edge (the app serves none), and the landing page carries `noindex`.

If you'd rather a large Timeline upload not cross Cloudflare, upload it on the LAN: on the
server, `ssh -N -L 8784:127.0.0.1:8784` still reaches the app, but signing in that way needs
G-4's temporary redirect URI back in Authentik for the duration.

## If a check fails

| Symptom | Cause and fix |
|---|---|
| 404 from Cloudflare on `/` after the route change | The Path field still holds the tracker rule, or the scope is still `tracker` (then the 404 carries the app's headers). |
| 502 or error 1033 | The route's URL is wrong (`localhost:8784`), or `web` isn't running (`./dev prod status`). |
| 411 on the token checks | **Disable Chunked Encoding** is off on the route. |
| `/auth/login` answers 503 | The app can't reach Authentik's discovery document: check `OIDC_ISSUER` in `.env.prod` and that `auth.adamcasada.com` answers. |
| Authentik says the redirect URI is invalid | The provider lacks `https://travel.adamcasada.com/auth/callback` (strict), or you used trips.* in the provider instead of travel.*. |
| "not in the group" | The user isn't in `travel-users`, or *Include claims in id_token* is off. |
| Sign-in refused after a password | The flow let a password through without a second factor; fix the Authenticator Validation stage (step 1.4). |
| 403 with a Cloudflare page | A zone security feature (Bot Fight Mode, a WAF rule) challenges the requests; changing it is a zone change, your call. |
| "site can't be found" | The home router remembers a failed lookup for up to 30 minutes (`~/infra/TUNNELS.md`); test on mobile data. |
| Everyone has to sign in again (with the second factor) every hour | Authentik's own session doesn't last: set the User Login stage's Session duration (step 1.4). |
| Every request answers 404, the tracker endpoints too | The route has an HTTP Host Header override: clear it (the app serves only its public names through the tunnel). |

## The go-live smoke test

`scripts/golive-smoke.sh`, as `./dev golive-smoke …`:

| Command | What it does |
|---|---|
| `./dev golive-smoke local` | Builds the production image from this checkout's `HEAD` (`git archive`, as a deploy does; uncommitted changes are left out), runs `db`, `migrate` and `web` with production's compose files and `.env.prod.example`'s settings plus scope `all` and a placeholder `https://` issuer, on `127.0.0.1` only (lane n: port 8805 + 10(n−1); main checkout: 8786), runs every check with the headers cloudflared adds, then removes the stack, its volume, its image and `var/golive-local/`. It waits until `free -m` shows 2,500 MiB available before building. Works in a lane. |
| `./dev golive-smoke local --keep` | The same, but leaves the stack running for manual testing (send `Host: travel.adamcasada.com` and `X-Forwarded-Proto: https`). `--port N` and `--issuer https://…` (a real provider's issuer, for sign-in) are optional. |
| `./dev golive-smoke local-check` / `local-down` | Run the checks again against the kept stack / remove it. |
| `./dev golive-smoke https://travel.adamcasada.com` | The checks through Cloudflare (`--scope tracker` before the flip; `--other HOST` or `--no-other` for the redirecting name, default `trips.adamcasada.com`). |

The local stack is its own compose project (`travel-history-golive`, or
`travel-history-golive-<item>` in a lane) with image tag `golive-local[-<item>]`: never
production's project, database, volumes, `.env.prod` or commit-tagged images. Locally it also
makes a synthetic account and tracker token in the throwaway database, so the accepted-token
checks run too, and a synthetic Member's sessions, to check that a trip can't be made public,
that a session past its hourly Authentik check is signed out and that `deactivate_account`
ends access at once; it checks the container itself (gunicorn, non-root, ports, Django's deploy
checks, the hourly check's setting, and that scope `all` refuses to start without the provider)
and that a loopback Host through the tunnel answers 404. `./dev prod smoke` stays the check of the running production stack;
`./dev prod tracker smoke` the check of the tracker-only `ingest` service.
