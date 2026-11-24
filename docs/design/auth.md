# Auth, access requests, email, push

Moved from PLAN.md §7 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 7. Auth, access requests, email, push

### 7.1 Login (OIDC relying party)

- **Library:** Authlib's Django OAuth client (state, nonce, PKCE S256, ID-token validation
  against the provider's JWKS) with ~50 lines of our own login/callback/logout/re-auth views.
  Users are matched on `(issuer, sub)`, never on email alone. See D-07 for why not
  mozilla-django-oidc or django-allauth.
- **Before any account is found or created** (D-103, `travel/accounts/provisioning.py`): the ID
  token must come from `OIDC_ISSUER` (compared without the trailing slash Authentik's issuers
  carry), list the `travel-users` group in its `groups` array, and, when it carries `amr`, show a
  second factor (G-5: `mfa`, or `user` for a passkey; `["pwd"]` alone is refused; no `amr` at
  all passes). A token Authlib refuses (signature, issuer, audience, expiry, nonce, `at_hash`)
  answers 400 and creates nothing. Tested against a synthetic Authentik in
  `tests/test_authentik.py`.
- **Sessions:** Django sessions (cookie `Secure` in production, `HttpOnly`, `SameSite=Lax`,
  rotated at login), CSRF on every unsafe method. The SPA is served from the same origin.
- **Re-authentication** for approvals and destructive admin actions: redirect to the provider
  with `prompt=login` and `max_age=0`, then require the ID token's `auth_time` to be within
  5 minutes before the confirm POST is accepted.
- **Android companion / API clients:** `Authorization: Bearer <access token>` validated locally
  (JWKS cached, `iss`, `aud`, `exp`, `alg=RS256`), mapped to the user by `(iss, sub)`.
- **Development:** `navikt/mock-oauth2-server` 6.1.2 in `compose.dev.yaml` (interactive login,
  any username; users `dev-admin`, `dev-member`, `dev-outsider` and their claims configured in
  `devstack/oidc/config.json`). Browser and Django reach it under
  the same host name (`TRAVEL_DEV_HOST`), because it derives the issuer from the Host header.

### 7.2 What this app needs from Authentik (for Adam to configure; not done from this repo)

Authentik 2026.8.x no longer needs Redis (removed in 2025.10): server + worker + PostgreSQL,
budget ~2–2.5 GB RAM (§21, §26).

1. **Group** `travel-users` (and `travel-admins` for Adam). Only members of `travel-users` may
   use this app; it is a per-app group, so a travel account does not unlock other apps.
2. **Web application + provider** "Travel History":
   - OAuth2/OpenID provider, client type **confidential**, signing key RSA (RS256),
     `sub_mode` = `hashed_user_id` (default; stable), issuer mode `per_provider`.
   - Redirect URIs (strict): `https://travel.adamcasada.com/auth/callback`; logout redirect
     `https://travel.adamcasada.com/` (Authentik: *Post-logout redirect URIs*, strict; the app
     sends `id_token_hint`, without which Authentik ignores the redirect).
   - **Until go-live only (G-4):** also the redirect URI `http://localhost:8784/auth/callback`
     and the post-logout URI `http://localhost:8784/`, for signing in over an SSH port-forward
     ([production guide](../production.md#signing-in-before-go-live-g-4)). Remove both at go-live.
   - Keep *Include claims in id_token* on (the default): the app reads `groups`, `email` and
     `name` from the ID token, not from the userinfo endpoint, so without it every sign-in is
     refused as "not in the group".
   - The client ID and secret go into `.env.prod` as `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`,
     the provider's issuer (`https://<authentik host>/application/o/<app slug>/`) as
     `OIDC_ISSUER`; production refuses to start with an issuer but no secret.
   - Scopes: `openid`, `email`, `profile` (claims used: `sub`, `email`, `name`,
     `preferred_username`, `groups`). Authentik reports `email_verified = false` by default, so the
     app trusts the email only because Authentik itself verified it at enrollment (the app never
     links accounts by email).
   - Application → **Policy/Group bindings → bind group `travel-users`**. Without a binding every
     Authentik user could log in.
3. **Native application + provider** "Travel Companion (Android)": client type **public**, PKCE
   S256 (the app always sends it), redirect URI (strict) `com.adamcasada.travel:/oauth2redirect`,
   scopes `openid profile email offline_access`, same signing key, same group binding. The API
   accepts tokens from both providers' `iss`/`aud` pairs, and only those that list
   `travel-users` in `groups` (and, when they carry `amr`, a second factor), checked on every
   request (D-108): phase 9 confirms Authentik's access tokens carry the profile scope's
   `groups` claim.
4. **Enrollment by invitation:** the `Invitation-based Enrollment` blueprint, with the Invitation
   stage set to *not* continue without an invitation, single-use invitations, `fixed_data`
   prefilled with name and email, and the User Write stage adding new users to `travel-users`.
5. **Second factor required:** in the authentication flow, an Authenticator Validation stage with
   device classes WebAuthn (passkeys) and TOTP, `not_configured_action = configure` (forces
   enrollment of a second factor at first login), WebAuthn user verification `preferred`.
   Optionally passkey autofill on the Identification stage. The app checks the result too
   (G-5, D-103): Authentik's ID token reports `amr: ["pwd", "mfa"]` after a password and an
   authenticator and `["user"]` after a passkey, both accepted; a password alone (`["pwd"]`)
   is refused.
   **Session duration** on the flow's User Login stage: about the app's own 14 days (e.g.
   `weeks=2`) rather than the default `seconds=0` (until the browser closes). The app sends a
   browser session back through Authentik every hour (D-108) to see whether the account is still
   in `travel-users`; while Authentik's session lives that trip asks nothing, otherwise it is a
   full sign-in with the second factor each time (an installed phone app loses a browser-session
   cookie whenever it is closed). The app makes the trip itself (D-120): a page load is
   redirected by the server, and when an API call gets the re-check's 401 (its `detail` is the
   fixed sentence in `travel.accounts.sessions.DUE_DETAIL`) the SPA goes straight to
   `/auth/login?next=<the same page>` instead of showing its Sign in screen, at most once a
   minute per tab (a second re-check within the minute shows the screen, so a broken sign-in
   can't loop). Any other 401 (signed out, refused) shows the Sign in screen. To check in 40c-2
   against the deployed version.
6. **API token** for this app (user `travel-provisioner`, intent `api`) with permission to
   create users and invitations and add users to `travel-users`, used by the approval flow:
   `POST /api/v3/stages/invitation/invitations/` (+ `.../send_email/`) or
   `POST /api/v3/core/users/` + `POST /api/v3/core/groups/{uuid}/add_user/`.
7. **Email:** the same SMTP settings as the app (`AUTHENTIK_EMAIL__HOST/PORT/USERNAME/PASSWORD/USE_TLS/FROM`).
8. **Recommendation:** run Authentik as its own shared-infrastructure project/repo
   (`~/apps/authentik`, own compose project, own PostgreSQL, published through the tunnel at
   `auth.adamcasada.com`), since every app will depend on it and it has its own upgrade cadence.
   Back it up like this app (its DB holds the 2FA devices).

### 7.3 Request access (public)

- **Landing page** (`/`): what the site is, who runs it, the honesty notice, a big "Request
  access" button, and a "Sign in" link.
- **Form:** name, email, relationship, optional note. No account or password needed.
  Cloudflare Turnstile (dev uses the documented always-pass test keys) + per-IP and per-email
  rate limits. The response is always the same generic "thanks, Adam will get back to you".
- **Allowlisted emails** skip approval: an invitation is created immediately.
- **Personal invite link / QR code:** `/invite/<token>` (single-use, expiring, stored hashed)
  pre-fills the form; the Admin generates it in the admin page and can show it as a QR code.
- **Approval:** a push notification (§7.5) and an email reach the Admin; tapping opens
  `/admin/requests/<id>`, which forces a fresh login (`prompt=login`, `auth_time` ≤ 5 min) and
  shows Approve / Reject buttons (CSRF-protected POST; nothing happens on GET).
- **On approval:** the app calls the Authentik API to create an invitation (or user) with the
  person's name/email, adds them to `travel-users`, and emails them the setup link. In
  development an `IdentityProvisioner` stub records the call and the dev mail catcher shows the
  email.
- **First login → onboarding:** honesty notice, link the account to an existing person (if the
  Admin pre-created one), Google Timeline export how-to (Android and iPhone), live-tracking setup
  with QR codes, pending transfer offers (§23 phase 8).

### 7.4 Email

- **Provider recommendation: Resend** (free plan 3,000/month, 100/day, 3 domains, 30-day logs;
  its SPF/bounce records live on the `send.` subdomain, so the apex records used by Cloudflare
  Email Routing stay untouched). SMTP2GO (1,000/month, 200/day) is the fallback choice.
- **Generic SMTP settings**, shared with Authentik so switching to a self-hosted relay later is a
  config change: `SMTP_HOST=smtp.resend.com`, `SMTP_PORT=587` (STARTTLS), `SMTP_USER=resend`,
  `SMTP_PASSWORD=<API key>`, `SMTP_FROM=noreply@adamcasada.com`.
- **Development:** Mailpit (SMTP on the internal network, web UI on the LAN dev port).
- **DNS records to add in Cloudflare** (values for DKIM come from the Resend dashboard when the
  domain is added; set them **DNS only**, not proxied):

  | Type | Name | Value | Notes |
  |---|---|---|---|
  | MX | `send.adamcasada.com` | `feedback-smtp.us-east-1.amazonses.com` (priority 10) | bounce handling; region shown in dashboard |
  | TXT | `send.adamcasada.com` | `v=spf1 include:amazonses.com ~all` | SPF for the return-path subdomain |
  | TXT | `resend._domainkey.adamcasada.com` | `p=<public key from Resend>` | DKIM |
  | TXT | `_dmarc.adamcasada.com` | `v=DMARC1; p=none; rua=mailto:dmarc@adamcasada.com` | start in monitor mode; after 2–4 clean weeks → `p=quarantine`, later `p=reject` |

  The apex SPF (`v=spf1 include:_spf.mx.cloudflare.net ~all` if Cloudflare Email Routing is on)
  needs no change: DMARC aligns through DKIM (`d=adamcasada.com`) and the `send.` return path.
  Never publish a second SPF record on the same name (RFC 7208: permerror). If a DMARC record
  already exists, edit it rather than adding another.

### 7.5 Push channel: Web Push (VAPID) via the PWA, ntfy as an optional adapter

- **Choice: Web Push** (`pywebpush`, VAPID keys in `.env`). No extra daemon, no extra account;
  every user already installs the PWA, and the same channel later serves family notifications
  (transfer offers, contribution activity). On Android/desktop the notification carries a
  "Review" action button; on iOS (16.4+, home-screen PWA only, no action buttons) tapping the
  notification opens the same page.
- One-tap approve = tap the notification → approval page → forced re-auth → Approve. Re-auth
  makes a stolen phone or a leaked link insufficient.
- Email to the Admin is sent in parallel as a fallback.
- `notify` is an adapter interface (`webpush`, `email`, `ntfy`), so ntfy (self-hosted, with
  `upstream-base-url: https://ntfy.sh` for iOS) can be added later without code changes
  elsewhere. Decision D-09.

### 7.6 Public route allowlist

Only these work without a session: `/` (landing), `/auth/login`, `/auth/callback`,
`/request-access`, `/invite/<token>`, `/api/v1/ingest/owntracks`, `/api/v1/ingest/overland`
(device token required), `/t/<slug>`, `/u/<profile>/…`, `/pm/<id>/<size>` (public media),
`/static/…`, the SPA's static files (`/app/assets/…`, `/app/icons/…`,
`/app/manifest.webmanifest`, `/app/sw.js` — code and icons only, no data), `/healthz`. The SPA
itself lives under `/app/` and is behind the wall. A test walks the URL resolver
and asserts every other route rejects anonymous requests. The API's docs and schema
(`/api/v1/docs`, `/api/v1/openapi.json`) don't exist in production and need a signed-in
session in development (D-107).

### 7.7 Hardening checklist

No published DB ports · non-root containers · own Docker networks (`internal: true` for the DB)
· `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER` for the tunnel ·
`SECURE_HSTS_SECONDS` once public · CSP · `X-Content-Type-Options` · `Referrer-Policy:
same-origin` · `ALLOWED_HOSTS` explicit · `DEBUG` off by default · secrets only in `.env` (0600)
· upload size limits · rate limits on public and ingestion routes.

Enforced since item 40a (D-96, [production guide](../production.md)): every production process
sets `TRAVEL_PRODUCTION`, and `settings.py` refuses to start unless the settings above hold
(`production_problems` in `travel/core/exposure.py`; HSTS required once `TRAVEL_PUBLIC_SCOPE=all`,
and `RATELIMIT_CLIENT_IP_HEADER=CF-Connecting-IP`; since item 40c-1 also a confidential client,
the group and the second-factor rule, D-103). The redirect to HTTPS is
`HttpsRedirectMiddleware`'s: it serves plain HTTP only to `/healthz` and to the server's own
loopback names without the tunnel's headers (the SSH port-forward, G-4). `/`, `/auth/login`
and `/auth/callback` are limited per address (60 a minute; 30 per 10 minutes each).
`./dev prod smoke` checks the rest (ports, networks, non-root, `.env.prod` mode, headers,
anonymous refusals).

Since item 42a (D-107 to D-109, the 41a review's fixes): the CSP and X-Frame-Options middleware
wrap WhiteNoise, so the installed PWA's `index.html` (which the service worker answers every
navigation with), `sw.js` and the assets carry them; request bodies are limited per endpoint
before anything reads them (32 MiB upload chunks, 5 MiB tracker posts, 2.5 MiB everything else);
production has no API docs or schema URL; bearer tokens the provider can't vouch for (or that it
is too slow to check) are no user, with a 30-second back-off; a request through the tunnel whose
Host isn't a public name answers 404; scope `all` needs the provider configured; browser
sessions go back through the provider hourly (`OIDC_SESSION_RECHECK_SECONDS`; the SPA redirects
to sign-in by itself, D-120), so an account removed from `travel-users` loses access within the
hour, and a refused sign-in ends the
browser's session; no trip can be made public until T37.

### 7.8 Account handover and linking (server commands)

Three owner-role commands (D-104, D-108, `travel/accounts/handover.py`), run with
`./dev prod manage` and never reachable from the app. All take ids only (without arguments they
list what to choose from), change nothing without `--execute`, run in one transaction, and write
an `accounts_auditlog` row and a log line.

- **`rebind_identity NEW OLD` (G-3, item 40c-3):** Adam's first Authentik sign-in creates an empty
  account NEW, because accounts are never matched by email. The command moves NEW's identity
  (issuer, subject, email, name) onto OLD, the account copied from dev that holds his data, so
  every row stays put, then deletes NEW (its default purposes and UI preferences go with it)
  and both accounts' sessions. It refuses unless NEW is a brand-new active Member with an
  identity from `OIDC_ISSUER`, no person and no other rows (checked over every foreign key to
  `accounts_user`), newer than OLD, and OLD is active without a real identity yet.
- **`deactivate_account ACCOUNT` (item 42a, D-108):** ends someone's access at once instead of
  at the next hourly provider check: `is_active = false` (the account then reads nothing, D-53,
  its tracker tokens stop working, its data stays) and every session it has deleted. It refuses
  the only active Admin. `--reactivate` lets the account in again; `--sign-out` only deletes its
  sessions (a lost phone of someone who keeps their access).
- **`link_person ACCOUNT PERSON`:** links a family member's account to the person Adam already
  put on trips (the linking step of the onboarding in §7.3, pulled forward from T33). Trips
  default to `participants` visibility (permissions.md §6.2), so until then the account can't
  see the trips its person is on. It refuses a person another account has and an account that
  already has a person.

Tests: `tests/permissions/test_account_commands.py` (as `travel_app`: the commands and their
statements are refused; after them, row-level security shows the kept rows, the moved identity,
the linked person's trips and nothing for a deactivated account, whose sessions answer 401;
every refusal leaves the database unchanged).
