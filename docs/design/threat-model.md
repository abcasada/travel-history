# Threat model

Moved from PLAN.md §20 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 20. Threat model

Assets, in order of sensitivity: raw location history and home addresses; trip details and
participants; photos; account access; the server itself.

| Surface | Threats | Mitigations |
|---|---|---|
| Login wall | Unauthenticated access to private routes | Middleware denies everything except an explicit public allowlist (login/callback, request access, invite landing, ingestion, public pages/profiles, static/PWA assets); a test enumerates all URL patterns and asserts each private one rejects anonymous requests. |
| OIDC | Token theft, CSRF on login, account confusion | Proven library; PKCE + `state` + `nonce`; users keyed by `(issuer, sub)` not email; Authentik group restricts who can log in; session cookies `Secure`, `HttpOnly`, `SameSite=Lax`; session rotation at login; short re-auth window (`max_age`/`auth_time`) for approvals and destructive admin actions. |
| CSRF / XSS | Cross-site writes, script injection via notes/titles | Django CSRF on all unsafe methods; React escapes by default; markdown rendered with a sanitizer; strict CSP (no inline script, `frame-ancestors 'none'`); uploads never served from the app origin as HTML. |
| Tracker tokens | Theft (logged URLs, screenshots), brute force, flooding, writing into someone else's history | 32 random bytes (`trk_` + base64url; guessing is hopeless, and the per-address limit bounds attempts), stored as SHA-256 only (CHECK constraint), shown once; write-only (cannot read anything; responses carry no data); writes only into the owner's history (RLS + device check, history migration 0009); per-token (120/min) and per-address (600/min) rate limits, 5 MB / 1,000-point cap, strict schema; revocable (final); last-used shown; Overland token accepted in header or query (its app supports only URL in some versions). The first middleware strips the header and query token from the request, every log line is redacted, `mail_admins` is off, and the access log omits query strings (§9.1). Any TLS-terminating proxy in front (e.g. Cloudflare) sees tokens and payloads in transit. |
| Request access | Spam, enumeration, abuse of approval | Turnstile + per-IP rate limit; generic responses (no "this email exists"); approvals need the Admin's fresh re-auth; invite tokens single-use, expiring, stored hashed. |
| Public pages | Leaking private fields, home location, precise times, other participants | Separate renderer + `travel_public` DB role + snapshot allowlist (§6.5); privacy zones; times off by default; consent per participant; sentinel leak tests; noindex for unlisted; slugs unguessable; rate limits. |
| Media | EXIF GPS leakage, malicious files | Re-encode to new JPEG/WebP (only capture time kept); Pillow decompression-bomb limit; type sniffing; size caps; originals never kept (Immich holds originals later). |
| Imports | Zip/JSON bombs, huge files, malformed data | Streaming parse with bounded memory; per-user upload quota; size cap per file (configurable, default 2 GB); worker memory limit; invalid rows reported, never fatal to the whole batch. |
| Routing proxy | Abuse as an open proxy, provider bans | Authenticated users only; per-user throttle; request validation (≤ 25 waypoints, NA polygon check); provider usage policies respected (§13). |
| Database | Direct access, privilege escalation | No published ports; separate roles; RLS; app role is not owner; secrets via `.env` (0600) never in git; backups encrypted with a key the server cannot decrypt. |
| Host / containers | Container escape, lateral movement to other apps | Non-root, `cap_drop: ALL`, `no-new-privileges`, read-only root filesystem where possible, own Docker networks, resource limits. |
| Operator access | Family members' privacy vs. the operator | Stated plainly (§6.7); the Admin role in the app cannot read private data, but the operator of the server can. |
| Backups | Theft from NAS, ransomware on the server | age-encrypted at source (public key on server, private key offline); NAS pulls and keeps immutable snapshots the server cannot delete. |
