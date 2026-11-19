# The production stack

Work-order item 40a, decision D-96 (pending Adam), G-1. The family's data lives here, never in
the development stack. Go-live (Authentik sign-in, the tunnel route, `TRAVEL_PUBLIC_SCOPE=all`)
comes in items 40c–40e; until then nothing here is reachable from the internet except, when
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
4. starts `db`, then `migrate` (owner role; a failed migration stops the deploy), then `web`,
   `worker` and `backup`; restarts `ingest` only if it was running;
5. waits for `web`'s health check, removes the images of all but the last two deployed
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
- behind the TLS proxy (`X-Forwarded-Proto` from cloudflared), HTTPS redirect, secure session
  and CSRF cookies; HSTS (1 year, subdomains) required once `TRAVEL_PUBLIC_SCOPE=all` and on
  the ingest-only service;
- `RATELIMIT_CLIENT_IP_HEADER=CF-Connecting-IP` (per-address limits use the visitor's address,
  not the tunnel's);
- CSP with `default-src` and `frame-ancestors 'none'`, nosniff, `Referrer-Policy: same-origin`,
  `X-Frame-Options: DENY`, and the middleware that sends them;
- upload size limits set;
- no OIDC back channel (D-57 is development only) and an `https://` issuer (no mock provider).

Per-address rate limits cover `/` (60 a minute), `/auth/login` and `/auth/callback` (30 each per
10 minutes), alongside the tracker endpoints' own limits. Containers run as the host user (the
database as uid 999), with all capabilities dropped, `no-new-privileges`, memory limits and log
rotation; `web` and `ingest` have read-only root filesystems. The database publishes no port.

`.env.prod` holds the secrets and must stay mode 0600; every `./dev prod` command checks that.
Adam adds `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` (item 40c) and
`AGE_RECIPIENT` himself, then runs `./dev prod up` to apply them (it recreates only the
containers whose settings changed, with the deployed image).
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
`localhost:8784` (G-4, item 40c).

## The smoke test

`./dev prod smoke` (`scripts/prod-smoke.sh`, also the last step of every deploy) checks:

- **The stack:** `web` runs the release image under gunicorn; no mock OIDC, Mailpit or Vite;
  every container non-root, none mounting the working tree; the database on an internal
  network only production containers join, with no published port; `web` published on
  `127.0.0.1:8784` only; `.env.prod` 0600; bulk storage outside any git working tree.
- **Health and the landing page:** `/healthz`, and `/` over HTTPS with HSTS, nosniff,
  X-Frame-Options, Referrer-Policy, COOP and CSP, no cookies, noindex, and only a "Sign in"
  link; plain HTTP redirected; an unknown host refused without DEBUG's page; the SPA build
  present.
- **Private paths:** every API operation in the release's OpenAPI schema answers 401
  anonymously, and the SPA and re-auth pages send you to sign in.
- **Public names:** before go-live, 404 on the canonical name except the tracker endpoints;
  the redirect from trips.* (including a `//host` path) and its tracker exemption.
- **Development:** if the dev stack runs, `127.0.0.1:8780` answers 404 to both public names.

## Reference data (for item 40b)

40b replaces production's database with a copy of development's, which already holds the
GeoNames gazetteer and the airport and airline tables. The cached download files are needed
only to load them again (`load_gazetteer`, `load_flight_reference`). The gazetteer's pin is the
verified cached copy (D-94): GeoNames republishes its files daily at the same address, so a
fresh download no longer matches the pinned checksum. To keep the pin, copy the cache:

```sh
cp -a var/bulk/reference/. ~/apps/travel-history-prod/bulk/reference/
./dev prod manage load_gazetteer        # only if the copy didn't bring the rows
```

or re-pin to today's files with `./dev prod manage load_gazetteer --latest` (downloads about
85 MB; the new checksums are recorded in the dataset versions).

## Memory

Measured with both stacks, Authentik and Valhalla running: resource-budget.md §21.4. The caps
are in `compose.prod.yaml`.
