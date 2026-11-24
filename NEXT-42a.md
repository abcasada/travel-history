# NEXT-42a (lane 2, branch item/42a)

Go-live hardening from 41a (docs/review/2026-11-24-go-live.md): F-1 to F-3 and F-6 to F-11 done.
Decisions D-107 to D-111 (after main's D-106). No migration; the OpenAPI schema is unchanged
(export diffed against the committed one), so no client regeneration.

- **F-1** CSP and X-Frame-Options middleware moved before WhiteNoise; `production_problems`
  refuses another order (D-107).
- **F-2** `travel.core.bodylimit.BodySizeLimitMiddleware`: 413 by declared length before any
  parsing; chunk PUT 32 MiB, tracker 5 MiB (the tracker view reads with a bounded
  `request.read`), else `DATA_UPLOAD_MAX_MEMORY_SIZE` = 2.5 MiB (production refuses > 5 MiB).
- **F-3** (D-108) sessions are stamped at the callback (`travel/accounts/sessions.py`) and,
  once older than `OIDC_SESSION_RECHECK_SECONDS` (compose.prod.yaml forces 3600; 0 = off in
  dev and tests), the next request ends them (401 with a reason, pages redirect to sign-in);
  a refused sign-in ends the session; bearer tokens are checked for `travel-users` and `amr`
  on every request; `deactivate_account [ID] [--reactivate|--sign-out] [--execute]` (owner
  role, ids only, dry run, audited, refuses the only active Admin). Matrix row
  `deactivate_alice` (109 actions × 7 actors), permissions.md §6.3 updated.
- **F-6** (D-111) digests refreshed (python `cf50a4f6…`, node `a6155384…`, postgis
  `4a43e3c3…`; all > 14 days old) in Dockerfiles, compose files, `dev` (three node lines,
  outside the lane subcommand), `scripts/stack.sh` and the fixture scripts; those images still
  carry openssl 3.5.7, so the backend base stage and the backup image run `apt-get upgrade`
  (openssl 3.5.9 now). CPU smoke on the non-AVX host passed for the dev and backup images.
- **F-7** no `/api/v1/docs` or `openapi.json` in production (dev: signed-in session only);
  `requests` errors in `OidcBearer` → no user, 30 s back-off, junk tokens never fetch keys.
- **F-8** `CF-Connecting-IP` with a non-public Host → 404 (ingest-only service exempt).
- **F-9** scope `all` needs `OIDC_ISSUER` (https) and the client id and secret.
- **F-10** (D-109) `public` → 422 on create, PATCH, bulk (Pydantic validator, schema
  unchanged) and in the services (purpose defaults, `public_mode` alone).
- **F-11** (D-110) dev-copy pruning and `e2e_cleanup` cover "E2E …" persons, tags `e2e` and
  `e2e-bulk-…`, SYNTHETIC trip-sheet batches (workbook title starts with SYNTHETIC; the
  template's doesn't) and their key links; `e2e_cleanup` keeps raw files (rule 12), the copy
  prunes SYNTHETIC raw files no batch uses. `./dev e2e` is unchanged.
- Smoke: `scripts/golive-smoke.sh` gained checks for F-1, F-2, F-3, F-7, F-8, F-9, F-10 (a
  synthetic Member's sessions in the throwaway DB). Docs: auth.md §7.2 (Authentik session
  duration, Android tokens need `groups`), §7.6–§7.8, go-live.md ("Removing someone's access",
  lost phone, two failure rows), production.md, phases 8.0d, facts register.

**For the merge / delta review:**
- 40c-2 must set Authentik's User Login stage Session duration (`weeks=2`), or everyone signs
  in with the second factor hourly (go-live.md step 1.4). Confirm the Authentik facts in the
  facts register against the deployed version.
- The SPA shows its Sign in screen when the hourly check is due (one tap, silent at
  Authentik). A follow-up could redirect automatically on the 401's reason.
- Lane isolation gap seen: `./dev build backup` in a lane retags the shared
  `travel-history-backup:latest` (running containers keep their image; `./dev up` rebuilds).
- `dev` changed only in the three node digest lines (lane 1 edits the lane subcommand).
