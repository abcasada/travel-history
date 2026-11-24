# NEXT-40d (lane 1, branch item/40d)

Handoff for the orchestrator; fold into NEXT.md at merge.

- **Done:** docs/go-live.md (Authentik checks incl. removing G-4's URIs, adding a family member
  via `link_person`, tunnel routes travel.*/trips.* → `localhost:8784` with the tracker path rule
  retired, DNS, scope flip, rollback, what Cloudflare sees, failure table); D-105;
  `scripts/golive-smoke.sh` = `./dev golive-smoke local [--keep] | local-check | local-down | https://<host> [--scope all|tracker]`;
  tracker-smoke.sh accepts Cloudflare's bare 404s and managed robots.txt through the tunnel;
  phases.md 8.6, exposure.md, production.md, PLAN.md index updated.
- **Local mode proof (lane 1):** fresh `./dev golive-smoke local` PASS (stack, landing, sign-in
  503 with the placeholder issuer, 75 API ops 401, 404s, trips redirect, ingest with a synthetic
  token on both names, chunked 411, logs clean), then everything removed (no containers,
  volumes, networks, image tag or var/golive-local).
- **For 41a:** in its own lane or any checkout of main: `./dev golive-smoke local --keep`, poke at
  `http://127.0.0.1:<port>` (lane n: 8805+10(n−1), main 8786) with `Host: travel.adamcasada.com`,
  `X-Forwarded-Proto: https`, `CF-Connecting-IP: 192.0.2.10`; `local-check`; `local-down`.
  `--issuer https://…` points sign-in at a real provider (the 302/state/nonce/PKCE branch is only
  exercised then, or remotely in 40e).
- **Finding for 41a (not fixed, out of scope):** anonymous `GET /app/assets/<unknown>` answers 200
  with the SPA shell (index.html, no data): the wall lets `/app/assets/` through and `spa_index`
  answers any `/app/` path. The smoke reports it as a note.
- **Tests (lane 1):** lint clean; `./dev test-quick` 2580 passed + 31 deselected, frontend 105 passed.
- **For the orchestrator:** CLAUDE.md's command list could gain `./dev golive-smoke` (I didn't
  edit CLAUDE.md). D-105 may collide with lane 2's numbers; renumber at merge if so.
