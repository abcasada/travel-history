# NEXT-40c-1

Lane handoff for work-order item 40c-1 (Authentik sign-in build). Fold into NEXT.md at merge.

- **Done (2026-11-23):** production OIDC for Authentik (D-103): issuer from `OIDC_ISSUER` (slash
  either way), `travel-users` as a list, `amr` second factor (G-5: `mfa` or passkey `user`;
  `["pwd"]` refused; no `amr` passes), token-validation errors 400 (were 500), confidential
  client required in production. G-4: `HttpsRedirectMiddleware` replaces Django's SSL redirect
  so plain HTTP on localhost (no tunnel headers) is served; public names unchanged; smoke test
  updated. Owner-role `rebind_identity NEW OLD` / `link_person ACCOUNT PERSON` (D-104; dry run
  unless `--execute`; ids only). Tests: `tests/test_authentik.py` (real Authlib against a
  synthetic Authentik), `tests/permissions/test_account_commands.py` (RLS-level),
  `tests/test_production.py` (G-4). Docs: auth.md §7.1/7.2/7.7/7.8, production.md (G-4 sign-in,
  G-3 handover), permissions.md §6.3 note, phases 8.0c, facts register. In this lane:
  `./dev test-quick` 2429 + 105 passed; `./dev e2e` green (mock sign-in through the new checks;
  only the known glyph 404); lowest available RAM 4.9 GiB with 14c-1 running.
- **Merge notes:** decisions are D-103/D-104 (renumber if 14c-1 took them). Outside the planned
  footprint: `scripts/prod-smoke.sh`; permissions.md §6.3 (one row cell + a note after the
  Accounts note). Read-only imports from `trips` (Purpose) and `core.devcopy`.
- **40c-2 needs from Adam:** the Authentik provider per auth.md §7.2 (confidential, per-provider
  issuer, include claims in id_token, `travel-users` binding, forced second factor), with the
  canonical redirect + post-logout URIs and G-4's temporary `http://localhost:8784/auth/callback`
  and `http://localhost:8784/`; `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` in
  `.env.prod`; stop entering data in dev before the final copy. First sign-in: Chrome or
  Firefox over `ssh -N -L 8784:127.0.0.1:8784` (production.md "Signing in before go-live").
- **Open:** Android bearer tokens (phase 9) carry the Android provider's own issuer, so the
  `(iss, sub)` lookup in `OidcBearer` won't find web-created accounts; needs a mapping then.
  Authentik `amr`/end-session facts were read from its main branch, not the deployed version.
