# Research: Authentik, OIDC libraries, email, push, Cloudflare, Android (checked 2026-10-19)

Confidence H/M/L. Source keys at the end. Not verified: Cloudflare Zero Trust free seats.

## Authentik
| Fact | Value | Conf | Src |
|---|---|---|---|
| Latest | 2026.8.4 (2026-10-14) | H | A1 |
| Redis | Removed in 2025.10 ("no longer uses Redis at all"); tasks moved 2025.8, sessions 2025.4 | H | A2, A3 |
| Side effect | ~50% more Postgres connections | H | A2, A3 |
| Compose | `postgresql` (postgres:16-alpine), `server`, `worker`; image `ghcr.io/goauthentik/server:2026.8.4`; ports 9000/9443; `.env`: `PG_PASS`, `AUTHENTIK_SECRET_KEY` | H | A4, A5 |
| Minimum | 2 CPU cores, 2 GB RAM | H | A4 |
| Real RAM | server 500–800 MiB; worker ~0.5 GiB (2025.12) → ~1 GiB (2026.2, #20537); #25683 retention fixed by `MALLOC_ARENA_MAX=2`, `MALLOC_TRIM_THRESHOLD_=131072`. Budget ~2–2.5 GB incl. Postgres | M | A6, A7 |
| OIDC endpoints | `/application/o/authorize/`, `/token/`, `/userinfo/`, `/revoke/`, `/introspect/`, `/application/o/<slug>/end-session/`, `/jwks/`, `/.well-known/openid-configuration` | H | A8 |
| Scopes | `openid`, `email`, `profile`, `offline_access`, `entitlements`, `goauthentik.io/api` | H | A9 |
| `email` claims | `email`, `email_verified` (hard-coded False since 2025.10 → custom mapping if needed) | H | A9 |
| `profile` claims | `name`, `given_name`, `family_name`, `preferred_username`, `nickname`, `groups`, `picture` | H | A9 |
| Refresh tokens | only with `offline_access` requested and mapped | H | A8 |
| client_type | confidential / public | H | A10 |
| sub_mode | hashed_user_id (default), user_id, user_uuid, user_username, user_email, user_upn | H | A10 |
| issuer_mode | per_provider (default, `.../application/o/<slug>/`) or global | H | A8 |
| Redirect URIs | list of {matching_mode strict/regex, url, redirect_uri_type authorization/logout} | H | A10 |
| Custom URI schemes | allowed | M | A12 |
| PKCE | plain + S256; not enforced for public clients unless a challenge is sent → always send S256 | M | A12 |
| Signing | RS256 (RSA key) / ES256 (EC); access tokens are JWTs | H | A8, A11 |
| Lifetimes | code 1 min, access 1 h, refresh 30 d | H | A11 |
| Re-auth | `prompt=login`, `max_age` supported | H | A12 |
| Logout | back-channel (default) / front-channel, GA 2025.10 | H/M | A13 |
| Restrict to group | Application → Policy/Group/User Bindings; **no bindings = everyone has access** | H | A14 |
| App-specific roles | Application Entitlements (2024.12+) via `entitlements` scope | H | A14 |
| Invitations | Invitation stage; link `https://auth.example/if/flow/<flow-slug>/?itoken=<uuid>`; fields name, expires, single_use, flow, fixed_data | H | A15, A16 |
| Invitation API | `POST /api/v3/stages/invitation/invitations/`; `POST .../{uuid}/send_email/` | H | A10 |
| Users/groups API | `POST /api/v3/core/users/`, `POST /api/v3/core/groups/`, `POST /api/v3/core/groups/{uuid}/add_user/` `{"pk": n}` | H | A10 |
| API tokens | `POST /api/v3/core/tokens/` {identifier, intent: api, user, expiring}; `GET .../view_key/`; `Authorization: Bearer` | H | A10 |
| Auto-group on enrollment | User Write stage `create_users_group` | H | A10 |
| MFA | Authenticator Validation stage `not_configured_action` = configure; device classes static/totp/webauthn/duo/sms/email; `webauthn_user_verification`; passkey autofill via Identification stage `webauthn_stage` | H | A10, A17 |
| SMTP env | `AUTHENTIK_EMAIL__HOST`, `__PORT`, `__USERNAME`, `__PASSWORD`, `__USE_TLS`, `__USE_SSL`, `__TIMEOUT`, `__FROM`; test `ak test_email` | H | A18 |
| Captcha stage | supports Turnstile | H | A19 |

Design notes: separate public provider for Android (`aud` = its client_id); with per_provider
issuer mode the two providers have different `iss` → accept both pairs or use global issuer mode;
same signing key on both.

## Django OIDC libraries
| Library | Latest | Django | Notes | Src |
|---|---|---|---|---|
| mozilla-django-oidc | 5.0.2 (2025-12-19) | 4.2–5.2 declared; no 6.x | single provider, session login, PKCE; DRF auth calls userinfo per request | B1, B2 |
| django-allauth | 65.20.0 (2026-10-16) | 4.2–6.1 | very active (Codeberg); heavy for one provider | B1, B3, B4 |
| Authlib | 1.9.1 (2026-10-14), joserfc | any | thin client; ~40 lines of views | B1, B5 |
| drf-oidc-auth | 4.0.0 (2026-10-08) | — | revived after 2022–2026 gap; small | B1, B6 |
| PyJWT | 2.15.1 (2026-09-28) | — | `PyJWKClient` + `jwt.decode(..., algorithms=["RS256"], audience, issuer)` | B1 |

Recommendation from research: mozilla-django-oidc on Django 5.2 LTS, Authlib on 6.x; bearer
tokens via ~30-line DRF auth class on PyJWT.

Dev OIDC: **navikt/mock-oauth2-server 6.1.2** (2026-10-18, `ghcr.io/navikt/mock-oauth2-server:6.1.2`):
auth code + PKCE, interactive login (any username), `JSON_CONFIG` with `interactiveLogin: true`,
`tokenCallbacks[{issuerId, requestMappings[{requestParam: "subject", match, claims}]}]`. Issuer
derived from Host header → browser and Django must use the same hostname. Dex v2.46.0
alternative (static passwords). Soluto mock v0.12.1 less active.

## Email
| | SMTP2GO Free | Resend Free |
|---|---|---|
| Volume | 1,000/mo, 200/day (25/h until domain verified) | 3,000/mo, 100/day |
| Domains | 5 senders | 3 domains |
| Logs | 5 days | 30 days |
| SMTP | `mail.smtp2go.com` 2525/587/8025/80/25 STARTTLS, 465/8465/443 SSL | `smtp.resend.com` user `resend`, password = API key; 25/587/2587 STARTTLS, 465/2465 TLS |
| DNS | 3 CNAMEs (return path `em<id>`, DKIM `s<id>._domainkey`, tracking `link`); no SPF change | `MX send` → `feedback-smtp.us-east-1.amazonses.com` (10); `TXT send` `v=spf1 include:amazonses.com ~all`; `TXT resend._domainkey` `p=…` (DNS-only) |

Recommendation: **Resend** (3× volume, 30-day logs, records on `send.` subdomain don't touch the
apex MX/SPF). Settings: host smtp.resend.com, port 587, STARTTLS, user `resend`, password API key,
from noreply@adamcasada.com.

DMARC/SPF: one SPF record per name (RFC 7208 §3.2, multiple = permerror), max 10 lookups; Cloudflare
Email Routing apex SPF `v=spf1 include:_spf.mx.cloudflare.net ~all` needs no change for Resend.
DMARC start `_dmarc TXT "v=DMARC1; p=none; rua=mailto:…"` → quarantine → reject. DMARCbis = RFC 9989
(~May 2026) removes `pct`. Cloudflare DMARC Management free.

## Turnstile
Free: 20 widgets, 10 hostnames each, unlimited challenges. Siteverify
`POST https://challenges.cloudflare.com/turnstile/v0/siteverify` (secret, response, remoteip,
idempotency_key); token valid 300 s, single use. Test sitekeys: `1x00000000000000000000AA` pass,
`2x00000000000000000000AB` fail, `1x00000000000000000000BB` invisible pass,
`2x00000000000000000000BB` invisible fail, `3x00000000000000000000FF` interactive. Test secrets:
`1x0000000000000000000000000000000AA` pass, `2x0000000000000000000000000000000AA` fail,
`3x0000000000000000000000000000000AA` timeout-or-duplicate; dummy token `XXXX.DUMMY.TOKEN.XXXX`.

## Push
ntfy v2.32.0 (2026-10-18). iOS instant delivery from self-hosted ntfy needs
`upstream-base-url: "https://ntfy.sh"` (only message id + SHA256 of topic URL leave the server).
Action buttons up to 3 (`view`, `http`). Web Push on iOS 16.4+ only for home-screen web apps;
notification action buttons not supported on Safari/iOS (body tap works). pywebpush 2.5.0.
Research recommendation: ntfy for the admin approve push (view action → page that forces re-auth,
then CSRF POST); Web Push for end-user notifications later.

## Cloudflare Tunnel
Max request body 100 MB on Free (413 above). DNS-only not possible behind a Tunnel → chunked
uploads. Proxy read timeout 125 s (524) → process uploads async. Multiple hostnames per tunnel OK.
Access not required; if added, bypass `/api/*` bearer paths, ingestion and OIDC callbacks.

## Android
AppAuth-Android 0.11.1 (last release 2021-12; some PRs merged 2026-03; de facto standard).
Alternative kalinjul/kotlin-multiplatform-oidc 0.18.4. WorkManager 2.12.0 (2026-09-23). Android 15:
dataSync FGS limited to 6 h / 24 h. UIDT jobs (API 34+, `RUN_USER_INITIATED_JOBS`,
`setUserInitiated(true)`, scheduled while visible, no Jetpack support). Recommendation: UIDT on 34+,
WorkManager expedited + setForeground below; same resumable chunked uploader (< 100 MB chunks).

## Sources (accessed 2026-10-19)
A1 gh api repos/goauthentik/authentik/releases · A2 https://docs.goauthentik.io/releases/2025.10/ ·
A3 https://goauthentik.io/blog/2025-11-13-we-removed-redis/ ·
A4 https://docs.goauthentik.io/install-config/install/docker-compose/ · A5 https://docs.goauthentik.io/compose.yml ·
A6 https://github.com/goauthentik/authentik/issues/20537 · A7 https://github.com/goauthentik/authentik/issues/25683 ·
A8 https://docs.goauthentik.io/add-secure-apps/providers/oauth2/ ·
A9 https://github.com/goauthentik/authentik/blob/version/2026.8.4/blueprints/system/providers-oauth2.yaml ·
A10 https://raw.githubusercontent.com/goauthentik/authentik/version/2026.8.4/schema.yml ·
A11 .../authentik/providers/oauth2/models.py (2026.8.4) · A12 .../oauth2/views/authorize.py, token/authorization_code.py ·
A13 https://docs.goauthentik.io/add-secure-apps/providers/oauth2/frontchannel_and_backchannel_logout/ ·
A14 https://docs.goauthentik.io/add-secure-apps/applications/manage_apps/ ·
A15 https://docs.goauthentik.io/add-secure-apps/flows-stages/stages/invitation/ ·
A16 https://docs.goauthentik.io/users-sources/user/invitations/ ·
A17 https://docs.goauthentik.io/add-secure-apps/flows-stages/stages/authenticator_validate/ ·
A18 https://docs.goauthentik.io/install-config/email/ · A19 https://docs.goauthentik.io/add-secure-apps/flows-stages/stages/captcha/ ·
B1 PyPI JSON API · B2 https://github.com/mozilla/mozilla-django-oidc/blob/main/HISTORY.rst ·
B3 https://docs.allauth.org/en/latest/socialaccount/providers/openid_connect.html · B5 https://github.com/authlib/authlib ·
B6 https://github.com/ByteInternet/drf-oidc-auth · C2 https://github.com/navikt/mock-oauth2-server/blob/master/README.md ·
C3 https://dexidp.io/docs/connectors/local/ · D1 https://www.smtp2go.com/pricing/ ·
D3 https://resend.com/docs/knowledge-base/account-quotas-and-limits · D6 https://resend.com/docs/send-with-smtp ·
D7 https://support.smtp2go.com/hc/en-gb/articles/115004408567 · D9 https://resend.com/docs/knowledge-base/cloudflare ·
E1 https://developers.cloudflare.com/email-routing/setup/email-routing-dns-records/ · E2 https://www.rfc-editor.org/rfc/rfc7208 ·
E3 https://redsift.com/blog/dmarc-rfc-9989 · E4 https://developers.cloudflare.com/dmarc-management/ ·
F1 https://developers.cloudflare.com/turnstile/plans/ ·
F2 https://developers.cloudflare.com/turnstile/get-started/server-side-validation/ ·
F3 https://developers.cloudflare.com/turnstile/troubleshooting/testing/ · G2 https://docs.ntfy.sh/config/ ·
G3 https://docs.ntfy.sh/publish/ · G4 MDN browser-compat-data · H2 https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/ ·
H3 https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/ ·
H4 https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/ ·
I2 https://repo1.maven.org/maven2/net/openid/appauth/maven-metadata.xml ·
J2 https://developer.android.com/jetpack/androidx/releases/work · J3 https://developer.android.com/develop/background-work/services/fgs/timeout ·
J5 https://developer.android.com/develop/background-work/background-tasks/uidt
