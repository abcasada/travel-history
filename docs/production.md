# The production stack

Work-order item 40a, decision D-96 (pending Adam), G-1. The family's data lives here, never in
the development stack. Go-live (Authentik sign-in, the tunnel route, `TRAVEL_PUBLIC_SCOPE=all`)
comes in items 40c–40e ([go-live runbook](go-live.md)); until then nothing here is reachable from the internet except, when
tracking resumes, the two tracker endpoints through the `ingest` service.

## Why a separate stack

The development stack's database takes work-in-progress migrations from mounted code, the test
databases, the e2e and scale-test writes, and frequent restarts. Its web server is DEBUG
runserver, and anyone on the LAN can sign in at the mock provider as `dev-admin`. Production
shares none of that: its own compose project, database volume, networks, secrets and bulk
storage, and only code that is committed and pushed to `main`.

## Where things are

| What | Production | Development (for comparison) |
|---|---|---|
| Compose project | `travel-history-prod` (`compose.yaml` + `compose.prod.yaml`) | `travel-history` (`compose.yaml` + `compose.dev.yaml`) |
| Database volume | `travel-history-prod_db-data` | `travel-history_db-data` |
| Networks | `travel-history-prod_internal` (internal: true), `_egress`, `_edge`, plus the shared `valhalla` | `travel-history_internal`, `_egress`, `valhalla` |
| Settings | `~/apps/travel-history-prod/.env.prod` (0600) | `.env` in the repository (0600) |
| Bulk storage (`/bulk`) | `~/apps/travel-history-prod/bulk` | `var/bulk` in the repository (D-84) |
| Code | `~/apps/travel-history-prod/release`: a `git archive` of the deployed commit | the working tree, bind-mounted |
| Images | `travel-history-backend:<commit>`, `travel-history-backup:<commit>` (12 hex digits) | `travel-history-backend-dev:latest`, `travel-history-backup:latest` |
| Web | gunicorn (2 workers × 4 threads) with the production SPA build, `127.0.0.1:8784` only | runserver on `127.0.0.1:8780` and the LAN address; Vite on the LAN `:5173` |
| Tracker endpoint | `ingest`, `127.0.0.1:8783`, profile `tracker` (stopped while tracking is on hold) | none |
| Sign-in | Authentik (item 40c) | mock provider (`:8781`) |

Both stacks' `web` and `worker` also join the shared `valhalla` network, where the service name
`web` is therefore ambiguous; nothing resolves it there (the dev Vite server reaches `web` over
its own project's network). The databases are never on a shared network.

The production directory sits beside the repository, outside the git working tree, so
`git clean -fdx` can't delete `.env.prod` or the bulk storage. Set `TRAVEL_PROD_DIR` to use
another directory. Bulk storage moves to the replacement HDD together with the development
bulk directory (D-84): stop the stack, move `bulk/`, change `TRAVEL_BULK_DIR` in `.env.prod`,
deploy.

## Commands

All through `./dev prod` (`scripts/prod.sh`); `./dev prod help` lists them.

| Command | What it does |
|---|---|
| `./dev prod init` | Creates the production directory, its bulk folders and `.env.prod` with fresh database passwords and secret key (copies `ORS_API_KEY` from `.env` if set). Never overwrites an existing `.env.prod`. |
| `./dev prod deploy` | See [Deploying](#deploying). |
| `./dev prod up` | Applies `.env.prod` changes: recreates the containers whose settings changed, with the deployed image (no build, no new code). |
| `./dev prod status`, `ps`, `logs [service]` | The deployed commit and the containers; follow the logs. |
| `./dev prod migrate` | Runs the migrations as the owner role with the deployed image (deploy does this itself). |
| `./dev prod manage <command>` | A Django management command as the owner role, in a one-off `tools` container of the deployed image (with internet access for dataset downloads). |
| `./dev prod shell`, `./dev prod psql` | Django shell and psql, both as the owner role. |
| `./dev prod backup-now` | One encrypted backup into `bulk/backup-outbox`. Refuses without `AGE_RECIPIENT`. |
| `./dev prod restore-test` | Backup with a throwaway key, restore into a scratch database, compare every table's row count, the policies and the `app` functions, verify the raw files' checksums. |
| `./dev prod import-from-dev` | Replaces production's database with a pruned, verified copy of development's (see [Copying the data from development](#copying-the-data-from-development-item-40b-d-97)). Refused once production has a real sign-in identity. |
| `./dev prod import-test` | The same steps against scratch containers with SYNTHETIC data, including both refusals. |
| `./dev prod smoke` | The local smoke test (below). |
| `./dev prod down` | Stops the stack. The database volume stays. |
| `./dev prod tracker start\|stop\|logs\|ps\|smoke` | The internet-facing tracker endpoint (`ingest`, docs/tracking/exposure.md). `./dev tracker …` does the same. |

None of the development commands (`./dev up`, `test`, `manage`, `psql`, `e2e`, `restore-test` …)
can reach the production database: they use the other compose project, whose containers aren't
on production's internal network and don't know its passwords. Both wrappers name their compose
project explicitly, so an exported `COMPOSE_PROJECT_NAME` can't redirect them, and production
commands run compose with a cleared environment, so nothing exported in the shell can override
`.env.prod`.

## Deploying

`./dev prod deploy` refuses unless this checkout is on `main`, the working tree is clean, and
`HEAD` equals `origin/main` after a fetch. Then it:

1. extracts `git archive HEAD` into `release.new/` and builds both images from it, tagged with
   the commit's first 12 hex digits (the runtime target: the frontend's production build plus
   the backend, no test tools);
2. if production is already running and `AGE_RECIPIENT` is set, takes a backup with the
   currently deployed image (otherwise it warns);
3. swaps `release.new/` in as `release/` and appends the commit to `deploys.log`;
4. starts `db` and runs the migrations as the owner role; if one fails, the deploy stops and
   `web` and `worker` keep running the previous image (each migration is its own transaction);
5. recreates `web`, `worker` and `backup`, and `ingest` only if it was running;
6. waits for `web`'s health check, removes the images of all but the last two deployed
   commits, and runs the smoke test.

Every other `./dev prod` command uses the compose files of `release/`, never those of the
working tree, so later edits in the repository can't change production until the next deploy.
There is no automatic rollback: to go back, check out the earlier commit on a branch, revert on
`main` and push, then deploy (database migrations only move forward).

## Production settings, enforced at startup

`compose.prod.yaml` sets these itself, so `.env.prod` can't weaken them, and every production
process (web, worker, migrate, tools, ingest) has `TRAVEL_PRODUCTION=true`, which makes
`settings.py` refuse to start (ImproperlyConfigured, listing each problem) unless all of
auth.md §7.7 holds:

- `DEBUG` off; a generated secret key of 40+ characters (no placeholders);
- explicit `ALLOWED_HOSTS` (no `*`, no `.domain` wildcards) and at least one public host name;
- behind the TLS proxy (`X-Forwarded-Proto` from cloudflared), HTTPS redirect (by
  `HttpsRedirectMiddleware`, which serves plain HTTP only to `/healthz` and to the SSH
  port-forward on localhost, [below](#signing-in-before-go-live-g-4)), secure session and CSRF
  cookies; HSTS (1 year, subdomains) required once `TRAVEL_PUBLIC_SCOPE=all` and on the
  ingest-only service;
- `RATELIMIT_CLIENT_IP_HEADER=CF-Connecting-IP` (per-address limits use the visitor's address,
  not the tunnel's);
- CSP with `default-src` and `frame-ancestors 'none'`, nosniff, `Referrer-Policy: same-origin`,
  `X-Frame-Options: DENY`, and the middleware that sends them, placed before WhiteNoise so the
  installed PWA's own files carry them too (D-107);
- upload size limits set, and per-endpoint body limits (`BodySizeLimitMiddleware`; the default
  `DATA_UPLOAD_MAX_MEMORY_SIZE` at most 5 MiB, Django's 2.5 MiB by default, D-107);
- no OIDC back channel (D-57 is development only) and an `https://` issuer (no mock provider);
- a confidential client: `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` once `OIDC_ISSUER` is set
  (not on `ingest`, which signs nobody in), the `travel-users` group check and the second-factor
  rule (G-5) switched on, and no loopback name among the public host names (D-103);
- with `TRAVEL_PUBLIC_SCOPE=all`, the provider configured (`OIDC_ISSUER`, client id and secret,
  D-107), and browser sessions re-checked with the provider every 60 s to 24 h
  (`OIDC_SESSION_RECHECK_SECONDS`; `compose.prod.yaml` forces 3600, D-108).

Production serves no API docs and no `openapi.json` (D-107). A request through the tunnel
(`CF-Connecting-IP`) whose Host isn't a public name answers 404, so a tunnel "HTTP Host Header"
override can't get around the scope.

Per-address rate limits cover `/` (60 a minute), `/auth/login` and `/auth/callback` (30 each per
10 minutes), alongside the tracker endpoints' own limits. Containers run as the host user (the
database as uid 999), with all capabilities dropped, `no-new-privileges`, memory limits and log
rotation; `web` and `ingest` have read-only root filesystems. The database publishes no port.

`.env.prod` holds the secrets and must stay mode 0600; every `./dev prod` command checks that.
Adam adds `OIDC_ISSUER` (the Authentik provider's issuer,
`https://<authentik host>/application/o/<app slug>/`, with or without the final slash),
`OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` (item 40c; auth.md §7.2) and `AGE_RECIPIENT` himself,
then runs `./dev prod up` to apply them (it recreates only the containers whose settings
changed, with the deployed image).
Until `AGE_RECIPIENT` is set, the nightly backup only logs a warning and `backup-now` refuses.

## Public names

`TRAVEL_PUBLIC_HOSTS=travel.adamcasada.com,trips.adamcasada.com`, with
`TRAVEL_CANONICAL_HOST=travel.adamcasada.com`:

- **Before go-live** (`TRAVEL_PUBLIC_SCOPE=tracker`), the canonical name answers only the
  tracker endpoints; every other path is a bare 404.
- **trips.adamcasada.com** answers a permanent redirect (301) to the same path and query on
  `https://travel.adamcasada.com`, in both scopes. The target host comes from settings, never
  from the request, so it can't be turned into an open redirect. The tracker endpoints are
  served there directly, not redirected, so a phone set up with that name keeps working.
- **The development stack never answers a public name:** its `TRAVEL_PUBLIC_HOSTS` is empty,
  and a DEBUG server answers a bare 404 to every Host header Django would refuse (instead of
  DEBUG's error page, which shows settings and a traceback). If the tunnel were ever pointed
  at port 8780 by mistake, it would show nothing.

Until go-live, the web service is reached only over an SSH port-forward to
`localhost:8784` ([next section](#signing-in-before-go-live-g-4)).

## Signing in before go-live (G-4)

Item 40c-1, D-103. Before the tunnel route exists, Adam signs in to production through an SSH
port-forward from his own computer:

```
ssh -N -L 8784:127.0.0.1:8784 <user>@<server>
```

then opens `http://localhost:8784/` in Chrome or Firefox. The local port must be 8784, because
the Authentik provider lists the temporary redirect URI `http://localhost:8784/auth/callback`
(and the post-logout URI `http://localhost:8784/`) until go-live, when both are removed.

- The browser speaks plain HTTP to the forward, so `HttpsRedirectMiddleware` serves requests
  whose Host is `localhost`, `127.0.0.1` or `[::1]` and that carry neither `X-Forwarded-Proto`
  nor `CF-Connecting-IP` without redirecting them to HTTPS. Every request through the tunnel
  carries the public host name and both headers, so the public names keep the HTTPS redirect,
  HSTS and everything else; the port is published on 127.0.0.1 only.
- Nothing else is relaxed: the session and CSRF cookies stay `Secure` (Chrome and Firefox accept
  Secure cookies from `http://localhost`; Safari drops them, so sign-in loops there), CSRF checks
  the forward's own origin, and the public names still answer only the tracker paths until
  `TRAVEL_PUBLIC_SCOPE=all`.
- After go-live the exemption stays, but signing in over the forward stops working once the
  temporary URIs are gone from Authentik. Only someone with a shell on the server can reach
  127.0.0.1:8784 at all.

## The smoke test

`./dev prod smoke` (`scripts/prod-smoke.sh`, also the last step of every deploy) checks:

- **The stack:** `web` runs the release image under gunicorn; no mock OIDC, Mailpit or Vite;
  every container non-root, none mounting the working tree; the database on an internal
  network only production containers join, with no published port; `web` published on
  `127.0.0.1:8784` only; `.env.prod` 0600; bulk storage outside any git working tree.
- **Health and the landing page:** `/healthz`, and `/` over HTTPS with HSTS, nosniff,
  X-Frame-Options, Referrer-Policy, COOP and CSP, no cookies, noindex, and only a "Sign in"
  link; plain HTTP through the tunnel redirected (also with a loopback Host header), plain
  HTTP on localhost served without HSTS (G-4); an unknown host refused without DEBUG's page;
  the SPA build present.
- **Private paths:** every API operation in the release's OpenAPI schema answers 401
  anonymously, and the SPA and re-auth pages send you to sign in.
- **Public names:** before go-live, 404 on the canonical name except the tracker endpoints;
  the redirect from trips.* (including a `//host` path) and its tracker exemption.
- **Development:** if the dev stack runs, `127.0.0.1:8780` answers 404 to both public names.

For go-live itself ([go-live runbook](go-live.md)), `./dev golive-smoke local` runs the same image
with scope `all` against a throwaway database (any checkout, lanes included), and
`./dev golive-smoke https://travel.adamcasada.com` checks the public names through Cloudflare.

## Copying the data from development (item 40b, D-97)

Adam's real data (the Timeline import, batch 33, and the trips he typed in) was entered through
the development stack, so it moves into production as a copy of the development database, pruned
down to his account. `./dev prod import-from-dev` (repeatable; `scripts/prod.sh`, database half in
`backend/travel/core/devcopy.py`, `manage.py dev_copy`) does it in seven steps. The development
database is only read (`pg_dump`, `SELECT`s) and its raw files only copied; dev's web and worker
keep running. Production's database is untouched until step 7.

1. **Refusals** (`dev_copy check`, in production's current database): the two databases' applied
   migrations must be identical (deploy the commit dev runs first), and no production account may
   have a real sign-in identity: an `https://` issuer, since production refuses any other and the
   mock provider's is `http://`. Once Adam signs in through Authentik (item 40c), the copy is
   refused for good, because it would erase that account.
2. **Copy** into a staging database `travel_import` beside production's (created from
   `template1`, which holds the extensions): `pg_dump -Fc` in dev's database container piped
   straight into `pg_restore` in production's, so no dump file is ever written.
3. **Prune** the staging copy: first a dry run that prints the inventory per account and table
   (before and after), then the same in one committed transaction. Kept: `dev-admin` (set
   `TRAVEL_KEEP_ACCOUNT` to keep another), all its rows (batches, points, segments, roll-ups, trips,
   legs, stops, persons, routes, device tokens, tracker points) and the reference tables. Removed:
   every other account with every row that refers to it; the kept account's batches whose raw
   file starts with the `SYNTHETIC` fixture marker, with everything they imported; its e2e
   leftovers (trips, places and device tokens named `E2E …`); and the contents of the sessions,
   the job queue, the rate-limit counters and the routing cache. Pruning follows PostgreSQL's
   foreign keys, not Django's `on_delete` (most user references are DO_NOTHING): a NOT NULL
   reference to a removed row removes its row, a nullable one is set to NULL (and reported),
   repeated until nothing changes. It refuses to run in a database named `travel` (the live name
   in both stacks), so it can't prune dev by mistake.
4. **Verify** in dev and in the copy: the kept account's rows in every table that refers to an
   account, each of its batches' points (batch 33: 193,009), the policy count and the `app`
   function count must be identical, and only one account may remain. Any difference stops the
   copy with production unchanged. The rows the pruning removes from the kept account on purpose
   (its SYNTHETIC batches, as the pruning reported them, and rows named `E2E …`) are left out on
   both sides; anything else they cascade to (legs of an `E2E` trip, say) shows up as a
   difference and stops the copy.
5. **Raw files** the remaining rows reference are copied from dev's `raw/` into production's
   (`0444`; an existing file with other content stops the copy, raw files are never
   overwritten), then each is decompressed and checked against its recorded SHA-256 in the
   backup image. Files of pruned rows are never copied.
6. **Reference cache:** dev's `reference/` download cache (GeoNames, OurAirports, OpenFlights)
   goes to production's, without overwriting. The copy already brings the reference rows; the
   cache is needed only to load them again with the pinned checksums (D-94; or re-pin with
   `./dev prod manage load_gazetteer --latest`).
7. **Swap:** with `AGE_RECIPIENT` set, a backup of the database being replaced; then `web`,
   `worker`, `backup` (and `ingest`) stop, `travel` is dropped and `travel_import` renamed to
   `travel`, and the services start again and pass their health check.

`./dev prod import-test` (`scripts/import-from-dev-test.sh`) runs the same steps
(`scripts/import-from-dev.sh`) against two scratch PostGIS containers on an internal network,
migrated with the working tree's code and holding SYNTHETIC data only: a copy that prunes the
other account and the kept account's SYNTHETIC batch, a repeat, and both refusals (migrations
differ; a real identity in production), each leaving the scratch production unchanged. The
pruning itself has unit tests in `backend/tests/test_devcopy.py`.

The staging database and the temporary directory (`import.*` in the production directory, holding
only the migration list and the verification counts) are removed on exit, whatever happens.

The final copy runs in item 40c, right before Adam's first sign-in, so whatever he enters in dev
until then carries over. After that sign-in, item 40c moves his Authentik identity onto the copied
account ([below](#handing-the-copied-account-to-adams-authentik-sign-in-g-3)), and production
refuses `import-from-dev` from then on.

**Rehearsal, 2026-11-19 (item 40b):** the copy passed: the dry-run inventory showed `dev-admin`
(925,326 rows, including batch 33's 193,009 points, 53,438 segments and 678,836 roll-ups) and
`dev-member` (254 rows, including the two synthetic batches whose raw files were lost with the
HDD); after pruning, one account, 45 identical checks, 1 raw file verified, and
`./dev prod restore-test` passed (72 tables/checks, raw files 1/1). A second run, with the steps
moved into `scripts/import-from-dev.sh`, passed the same way (the raw file already in place was
compared, not copied again); dev still had its 2 accounts and 193,033 points. The backup gate (an encrypted
backup with the real key) stays open until `AGE_RECIPIENT` is set.

## Handing the copied account to Adam's Authentik sign-in (G-3)

Item 40c-3, with the commands built in 40c-1 (D-104, auth.md §7.8). Adam's first Authentik sign-in
creates a new, empty Member account, because accounts are matched by issuer and subject and never
by email. The copied account (`dev-admin`, Admin, all the data) still carries the dev mock's
identity, which production can't sign in with. Then:

1. `./dev prod manage rebind_identity` lists the accounts: the new one (Member, Authentik's
   issuer, only its default purposes) and the copied one (Admin, the mock's `http://` issuer,
   all the rows).
2. `./dev prod manage rebind_identity NEW OLD` is the dry run: it prints the identity that moves,
   the rows the copied account keeps, what is deleted with the empty account and how many
   sessions end.
3. The same with `--execute` does it in one transaction and writes an audit log row. Adam signs
   in again (his session ended) and lands on the copied account, still Admin.

It refuses anything else: the wrong way round, an account that owns data, an identity from
another provider, a target that already has a real identity. Afterwards `import-from-dev` is
refused for good (production has a real identity).

Family members (after go-live, [go-live runbook](go-live.md#adding-a-family-member)): once a member has signed in once,
`./dev prod manage link_person` lists accounts and the persons without one, and
`link_person ACCOUNT PERSON --execute` links the account to the person already on their trips,
so the trips shared with `participants` visibility appear.

Ending someone's access (D-108, [go-live runbook](go-live.md#removing-someones-access)):
`./dev prod manage deactivate_account` lists the accounts with their session counts;
`deactivate_account ACCOUNT --execute` deactivates it and deletes its sessions at once (dry run
without `--execute`; it refuses the only active Admin), `--reactivate` lets it in again, and
`--sign-out` only deletes its sessions (a lost phone). Each writes an audit log row.

## Memory

Measured with both stacks, Authentik and Valhalla running: resource-budget.md §21.4. The caps
are in `compose.prod.yaml`.
