# CLAUDE.md

Private, self-hosted website for cataloging a lifetime of travel for Adam and a few family
members. Django + GeoDjango + PostgreSQL/PostGIS backend, React + TypeScript + MapLibre PWA,
everything in Docker on Adam's home server. **`PLAN.md` is the source of truth** for design,
phases, decisions (§24) and open questions (§25). Read the relevant PLAN.md sections before
changing anything, and keep PLAN.md current.

## Project structure

```
PLAN.md                 design, phases + milestones, decisions log, open questions, facts register
CLAUDE.md               this file
dev                     ./dev wrapper: every tool runs in a container (no make/node on the host)
compose.yaml            production-like stack: db, migrate, web, worker, backup
compose.dev.yaml        dev overrides: mock OIDC, Mailpit, Vite, LAN port bindings
.env.example            all settings; real .env is git-ignored (0600)
backend/                Django project
  config/               settings, urls, wsgi
  travel/               apps: core (RLS, policy, ratelimit), accounts, trips, vehicles, history
                        (imports, points, segments, homes), geo (reference data), media, routing,
                        tracking (ingestion), public (separate renderer)
  tests/                pytest; permission matrix + RLS tests live in tests/permissions/
frontend/               React + TS + Vite PWA
  src/shells/           desktop and mobile shells
  src/platform/         adapters: files, shortcuts, notifications (wrapper-ready)
db/init/                role creation (runs once on first DB init)
devstack/               dev-only service config (mock OIDC users/claims)
backup/                 backup image + scripts (pg_dump → zstd → age), restore test
valhalla/               separate compose project `valhalla` (shared routing engine)
docs/                   guides (tracking setup, Timeline export, Authentik, email DNS, backups)
docs/research/          dated research notes behind PLAN.md's facts register
data/fixtures/          synthetic test data only (must contain the SYNTHETIC marker)
data/private/           Adam's real files — git-ignored, never committed
scripts/                repo tooling (personal-data guard, …)
.githooks/pre-commit    gitleaks (Docker) + personal-data guard
```

Directories appear as phases land; PLAN.md §23 tracks what exists.

## Commands

All commands run in containers through `./dev` (see `./dev help`):

- `./dev setup` — first-time: hooks path, `.env` from `.env.example`, bulk dirs
- `./dev up` / `./dev down` — start/stop the dev stack (db, web, worker, mock OIDC, Mailpit, Vite)
- `./dev test` — backend (pytest) + frontend (Vitest, type-check) tests; `./dev test-backend [args]`, `./dev test-frontend`
- `./dev lint` — ruff + Biome
- `./dev manage <cmd>` — Django management commands (`migrate` runs as the owner role)
- `./dev psql` — psql as the owner role (never expose the DB port)
- `./dev manage set_role <email> admin` — make a user Admin (after their first sign-in)
- Dev sign-in: open the app, choose Sign in, and type `dev-admin`, `dev-member` or `dev-outsider` (no group → refused) at the mock provider
- `./dev e2e [base-url]` — headless-Chrome smoke test of sign-in, honesty notice, map and both shells (dev stack; screenshots in `e2e/out/`)
- After changing the API: `./dev manage export_openapi > frontend/src/api/openapi.json && ./dev npm run gen:api` (commit both generated files)
- `./dev restore-test` — backup → restore into a scratch DB → verify
- Dev URLs (LAN/VPN only): app with hot reload `http://<lan-host>:5173/app/`, Django `:8780`, mock OIDC `:8781`, Mailpit `:8782`

## Coding conventions

- Python 3.13, Django 6.1, Django Ninja schemas for every endpoint; ruff for lint + format.
  Type hints on public functions. Business rules in plain functions/services, not in views.
- Every permission decision goes through `travel.core.policy` (one place) **and** is enforced by
  PostgreSQL RLS. Never filter by owner only in a view.
- Database: all user-owned tables have an owner/author column, RLS enabled, and policies for
  every command. RLS/trigger SQL lives in migrations (`RunSQL`) next to the model change.
  Runtime connects as `travel_app` (no ownership, NOBYPASSRLS); migrations as `travel_owner`;
  public pages as `travel_public`. The RLS user context is transaction-local
  (`set_config('app.user_id', …, true)`); never use session-level `SET`.
- Times: store UTC `timestamptz` + IANA zone name where local time matters. Geometry SRID 4326;
  use `geography` casts for distances.
- Frontend: TypeScript strict; API types generated from the OpenAPI schema; no direct calls to
  routing providers (only `/api/v1/routing/*`); platform-specific code only in `src/platform/`.
  Biome for lint + format.
- Tests are synthetic: factories and fixtures generate fake people, places and points. Fixture
  files with location data live under `*/fixtures/` and start with a `SYNTHETIC` marker.
- Comments explain why, not what. Match the surrounding code.

## How to work: autonomy and guardrails (from Adam's brief, word for word)

- **Working cadence:**
  - Work through the phases in order.
  - At every milestone, all tests pass, PLAN.md is updated, and you commit and push.
  - After each push, post a short summary: what's done, what's next, decisions you made, and open questions.
- **Decisions:** when something isn't covered here, choose the option you'd recommend, record it with your reasoning in the decisions log, and keep going.
- **Questions:** collect them in an Open Questions section of PLAN.md for me to answer when I can. Never block on them.
- **Stop and ask me first ONLY for:**
  - concluding that forking an existing project beats building fresh (see the prior-art evaluation);
  - changes to shared infrastructure: the existing reverse proxy, other sites' or apps' config, the firewall or router, DNS;
  - exposing anything to the internet;
  - the full North America Valhalla tile build, or anything else likely to exceed the resource budget. Until then, develop and test routing with a small regional extract, such as Kansas;
  - anything that needs my accounts, credentials, or payment: Authentik admin setup, SMTP provider signup, Cloudflare records, Turnstile keys, app-store publishing, GitHub settings beyond creating the repo;
  - deleting or overwriting real data, including raw import files;
  - installing packages or daemons on the host itself. Everything runs in containers.
- **If you're blocked on one of these,** finish everything else you can using dev stubs and synthetic data. Then leave me a clear checklist of what you need.
- **Missing real files:** if my Timeline export or flight spreadsheet isn't in `data/private/` yet, use synthetic fixtures and keep going.
- **Exposure:** never expose the app publicly before Authentik with 2FA is live. Until then, dev access is over LAN/VPN only.
- **Repo:** if the GitHub repo doesn't exist yet, create it as private.

## Standing rules

1. **No personal data or secrets in git.** No exports, real coordinates, real addresses, names of
   family members, tokens, keys, or `.env`. Real files go in `data/private/` (git-ignored). The
   pre-commit hook (gitleaks + `scripts/check-staged-data.sh`) must stay enabled
   (`git config core.hooksPath .githooks`); never bypass it with `--no-verify`. The repo must be
   safe even if public (it currently **is** public — PLAN.md Q-1).
2. **No code copied from AGPL or BSL projects** (TREK, Reitti ≥ 5, Dawarich, GeoPulse) — ideas
   only. No code copied from GPL projects (AdventureLog, AirTrail) either: it would make this
   project GPL-3.0 and the Android APK a GPL distribution. **MIT code (gpx.studio) may be ported
   with attribution**: keep the original copyright + permission notice in the file header and in
   `THIRD_PARTY_NOTICES.md`.
3. **Permission changes require tests** — at the API level and at the SQL/RLS level as
   `travel_app` — and an update to the matrix in PLAN.md §6.3.
4. **Public pages render only allowlisted fields** (PLAN.md §6.5): only the snapshot builder
   copies data into the public snapshot tables; public views read only those tables through the
   `travel_public` role. Any change needs the sentinel leak tests to pass.
5. **Never recompute a saved route.** Saved routes are frozen versions; edits create a new
   version. No code path may re-route or overwrite an existing `route` row.
6. **Never treat absence from a re-import as a deletion.**
7. **In-app edits beat imported changes.** Confirmed trips whose source data changed get a review
   flag; they are never silently changed.
8. **Photo originals belong in Immich, never copied into this app.** Basic photos are stored only
   as metadata-free display/thumbnail re-encodes.
9. **Everything runs in containers, with nothing installed on the host.** Use `./dev` or
   `docker compose run`. Host changes (packages, swap, LVM, firewall) need Adam's approval.
10. **Commit, push, and summarize at every milestone** (all tests passing first).
11. **Keep PLAN.md updated when decisions change**: decisions log (§24), open questions (§25),
    phase status (§23), facts register (§26) with source, date checked and confidence.
12. Raw import files are read-only and never deleted or overwritten without Adam's approval.
13. Outbound requests to third-party services never carry personal data (no emails or names in
    User-Agent headers, no raw location history to hosted routing APIs).
14. The DB port is never published; containers run as non-root; the app stays LAN/VPN-only until
    Authentik with 2FA is live.

## Environment notes

- Host today: Xeon W3565 (x86-64-v2, **no AVX**), 11 GiB RAM, small SSD (~28 GB free), 931 GB HDD
  at `/storage/hdd1`. Every native binary must run without AVX. Migration to a Ryzen 5 3600 /
  32 GB host is expected (PLAN.md §2, §21).
- Public ingress for the server's sites is a dashboard-managed Cloudflare Tunnel
  (`~/apps/cloudflared`, host networking); apps bind `127.0.0.1:<port>`. This app uses `8780`.
  Adding its hostname is a shared-infrastructure change (ask first).
- Bulk storage for this app: `/storage/hdd1/travel-history/{raw,media,backup-outbox}` → `/bulk`.
- Docker image tags are pinned; update deliberately and re-run the CPU smoke test.
