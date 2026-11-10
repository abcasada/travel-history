# Auth, access requests, email, push

Moved from PLAN.md §7 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 7. Auth, access requests, email, push

### 7.1 Login (OIDC relying party)

- **Library:** Authlib's Django OAuth client (state, nonce, PKCE S256, ID-token validation
  against the provider's JWKS) with ~50 lines of our own login/callback/logout/re-auth views.
  Users are matched on `(issuer, sub)`, never on email alone. See D-07 for why not
  mozilla-django-oidc or django-allauth.
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
     `https://travel.adamcasada.com/`.
   - Scopes: `openid`, `email`, `profile` (claims used: `sub`, `email`, `name`,
     `preferred_username`, `groups`). Authentik reports `email_verified = false` by default, so the
     app trusts the email only because Authentik itself verified it at enrollment (the app never
     links accounts by email).
   - Application → **Policy/Group bindings → bind group `travel-users`**. Without a binding every
     Authentik user could log in.
3. **Native application + provider** "Travel Companion (Android)": client type **public**, PKCE
   S256 (the app always sends it), redirect URI (strict) `com.adamcasada.travel:/oauth2redirect`,
   scopes `openid profile email offline_access`, same signing key, same group binding. The API
   accepts tokens from both providers' `iss`/`aud` pairs.
4. **Enrollment by invitation:** the `Invitation-based Enrollment` blueprint, with the Invitation
   stage set to *not* continue without an invitation, single-use invitations, `fixed_data`
   prefilled with name and email, and the User Write stage adding new users to `travel-users`.
5. **Second factor required:** in the authentication flow, an Authenticator Validation stage with
   device classes WebAuthn (passkeys) and TOTP, `not_configured_action = configure` (forces
   enrollment of a second factor at first login), WebAuthn user verification `preferred`.
   Optionally passkey autofill on the Identification stage.
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
and asserts every other route rejects anonymous requests.

### 7.7 Hardening checklist

No published DB ports · non-root containers · own Docker networks (`internal: true` for the DB)
· `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER` for the tunnel ·
`SECURE_HSTS_SECONDS` once public · CSP · `X-Content-Type-Options` · `Referrer-Policy:
same-origin` · `ALLOWED_HOSTS` explicit · `DEBUG` off by default · secrets only in `.env` (0600)
· upload size limits · rate limits on public and ingestion routes.
