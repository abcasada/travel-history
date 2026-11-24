# Development

Everything runs in containers through `./dev` (`./dev help`; the command list is in CLAUDE.md).
The main checkout's dev stack is the compose project `travel-history`; its database holds real
data (Adam's Timeline import, hand-entered trips), so tests and experiments that might disturb
it belong in a lane.

## Parallel lanes

Parallel build lanes (D-98, work-order item P1) let two builders work at once, each in its own
git worktree with its own dev stack. Only the main checkout's stack touches real data.

```
./dev lane new 40c-1          # from the main checkout
cd ../travel-history-lanes/40c-1
./dev test-quick              # its own DB container; the test DB is created there
./dev up && ./dev load-reference && ./dev e2e    # full stack, reference data, browser smoke
./dev lane list
cd ../../travel-history && ./dev lane rm 40c-1   # after the branch is merged into main
```

What `./dev lane new <item>` sets up:

- **Worktree and branch:** `../travel-history-lanes/<item>` on branch `item/<item>`, made from
  `main` (or the existing branch of that name).
- **`.env`:** built from `.env.example` with fresh secrets, never copied from the real `.env`.
  It names the lane (`TH_LANE`, `TH_LANE_ITEM`), and `./dev` refuses compose commands in a
  worktree whose `.env` doesn't.
- **Its own stack:** compose project `travel-history-lane-<item>`, so the DB volume, networks
  and containers are its own. Every image it builds is tagged `lane-<item>`
  (`travel-history-backend-dev`, `travel-history-backend`, `travel-history-backup`; D-121):
  `./dev` passes `TRAVEL_DEV_IMAGE_TAG` and `TRAVEL_IMAGE_TAG` from the lane's name, overriding
  its `.env`, so `./dev build` or `./dev up` in a lane never retags the main stack's images
  (`travel-history-backup:latest` included), also in lanes made before this. The main checkout
  passes neither, so its tags and rendered compose config are unchanged. The DB runs with
  `shared_buffers=256MB`.
- **Port block** (lane number n = 1, 2, …), bound to 127.0.0.1 only:

  | lane | web | mock OIDC | Mailpit | Vite | e2e browser (CDP) |
  |---|---|---|---|---|---|
  | main checkout | 8780 | 8781 | 8782 | 5173 | 9222 |
  | 1 | 8800 | 8801 | 8802 | 5180 | 9223 |
  | 2 | 8810 | 8811 | 8812 | 5190 | 9224 |

  8790 belongs to another app on this host, so lanes start at 8800.
- **Bulk storage:** the worktree's own `var/bulk`. `./dev` refuses a lane whose
  `TRAVEL_BULK_DIR` points outside its worktree. Only the public reference downloads in the main
  `var/bulk/reference` are copied in (GeoNames, OurAirports, OpenFlights). They're needed for
  `./dev load-reference` and the e2e, and GeoNames pins can't be downloaded again (D-94). Raw
  imports and media are never copied, and the main bulk is never mounted.
- **Valhalla:** lane stacks join the shared, stateless `valhalla` network like the main stack.
  Only the main checkout may run `./dev valhalla build|up|down`.
- **Refused in a worktree:** `./dev prod …` (including `import-from-dev` and `restore-test`),
  `./dev tracker …` and `./dev restore-test`.
- **The pre-commit hook** works in a worktree too: it mounts the common git dir, so gitleaks
  scans the staged changes there. It also refuses if gitleaks logs an error.

`./dev lane rm <item>` stops the lane's stack and deletes its volumes, image tags and worktree,
then deletes `item/<item>`, locally and on `origin`, once it is merged into `main`. "Merged"
means an ancestor of `main`, or, after a rebase that wasn't written back to the branch, every
commit has a patch-equivalent commit in `main` (`git cherry`). It deletes with `git branch -D`
because `-d` compares with the branch's upstream, which still holds the pre-rebase commits. It
refuses an unmerged branch or uncommitted changes unless `--force` is given, which keeps the
branch.

**The hourly re-check in a lane:** development turns it off (`OIDC_SESSION_RECHECK_SECONDS=0`).
To see the SPA's automatic sign-in redirect (D-120), add `OIDC_SESSION_RECHECK_SECONDS=15` to
the lane's `.env` (never the main one), `./dev up`, then `./dev e2e --recheck`: it signs in at
the mock provider, waits until the session is due, opens Trips and expects the provider's page
(no Sign in screen) and a return to `/app/trips`, then expects the Sign in screen for a second
re-check within the minute. Remove the line afterwards: the ordinary `./dev e2e` takes longer
than 15 seconds and would be sent to sign-in midway.

**Scratch files and logs:** lane builders run under one orchestrator session, so they share
its scratchpad directory. Put the item in every scratch file and log name
(`<scratchpad>/43a-test-quick.log`, not `test-quick.log`) so two lanes never overwrite each
other's output. Files inside the worktree (`e2e/out/`, `var/`) are already per lane.

**Memory:** each lane's test DB plus test run costs roughly a gigabyte, and a full lane stack
(with Vite and the mock OIDC server) more. When the host drops under about 2 GiB available
(`free -m`), run one lane only (docs/ORCHESTRATION.md).
